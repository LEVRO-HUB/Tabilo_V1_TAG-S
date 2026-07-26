"""
Tabilo — Faculty resignation recovery service (Phase 4a)

recover_from_resignation(teacher, term) reassigns a resigned teacher's
CourseRequirements for one term to other active, eligible staff via a full
solve_optimized() re-run, while protecting every other existing
TimetableCell from being touched by that re-solve, and rolling back
completely -- leaving the term byte-identical to before the call -- if no
feasible reassignment exists.

How "protect everyone else" actually works: it leans entirely on
core/solver/build.py's existing "skip a CourseRequirement that already has
ANY locked TimetableCell this term" simplifying rule, rather than adding
new solver logic. Every OTHER currently-unlocked cell gets temporarily
locked before the re-solve, so its CourseRequirement is excluded from the
model entirely (treated as already satisfied) -- only the resigning
teacher's own CourseRequirements (their cells were deleted, so they have no
locked cell to exclude them) are actually up for re-scheduling.

This function deliberately does NOT flip teacher.is_active itself. Marking
someone resigned and recovering their schedule are separate, independently
reviewable steps -- see core/management/commands/recover_resignation.py.
"""

from django.db import transaction

from core.models import CourseRequirement, SolverRun, TimetableCell
from core.solver.apply import apply_solution
from core.solver.build import solve_optimized


class _RecoveryInfeasible(Exception):
    """Internal signal used to unwind the recovery transaction on a
    non-FEASIBLE solve; carries the SolverResult out to the caller."""

    def __init__(self, result):
        self.result = result


def recover_from_resignation(teacher, term):
    if teacher.institution_id != term.institution_id:
        raise ValueError(
            f"{teacher.name} belongs to a different institution than term {term.name}."
        )
    if teacher.is_active:
        raise ValueError(
            f"{teacher.name} is still active. recover_from_resignation() does not deactivate "
            "teachers itself -- deactivate them first, then call this."
        )

    try:
        with transaction.atomic():
            # Step 1: snapshot genuine pre-existing pins -- these must stay
            # locked and completely untouched throughout.
            pre_locked_ids = set(
                TimetableCell.objects.filter(term=term, is_locked=True).values_list("id", flat=True)
            )

            # Step 2: temporarily lock every other unlocked cell so the
            # re-solve below leaves their CourseRequirements alone (see
            # module docstring for why this works).
            TimetableCell.objects.filter(term=term, is_locked=False).update(
                is_locked=True, locked_reason=TimetableCell.RESIGNATION_RECOVERY,
            )

            # Step 3: the solver must pick a replacement -- periods_per_week,
            # block_size, etc. all stay untouched.
            CourseRequirement.objects.filter(term=term, teacher=teacher).update(teacher=None)

            # Step 4: delete the resigning teacher's own cells outright --
            # they're about to be regenerated fresh, not left as stale
            # unlocked cells for apply_solution to clean up later.
            TimetableCell.objects.filter(term=term, teacher=teacher).delete()

            # Step 5.
            result = solve_optimized(term)
            if result.status != "FEASIBLE":
                # Step 6: do NOT manually undo steps 1-4 -- raising here lets
                # transaction.atomic()'s rollback handle it, so a failed
                # recovery is a complete no-op on the database.
                raise _RecoveryInfeasible(result)

            # Step 7: nothing stale to clear -- step 4 already deleted the
            # resigning teacher's cells, and everyone else's are locked.
            apply_solution(term, result.assignments)

            # apply_solution() only ever writes the chosen teacher onto
            # TimetableCell rows, never back onto CourseRequirement.teacher
            # (by design -- a null-teacher CR normally stays re-decidable on
            # every future solve). A resignation reassignment needs to be
            # durable instead: pin the replacement so future re-solves don't
            # unpredictably reshuffle who's covering these classes.
            teacher_id_by_cr_id = {a["course_requirement_id"]: a["teacher_id"] for a in result.assignments}
            for cr_id, replacement_teacher_id in teacher_id_by_cr_id.items():
                CourseRequirement.objects.filter(pk=cr_id).update(teacher_id=replacement_teacher_id)

            # Step 8: restore every cell temporarily locked in step 2.
            # Skipping this would permanently lock the whole term against
            # any future re-solve or weight-tuning run.
            TimetableCell.objects.filter(
                term=term, locked_reason=TimetableCell.RESIGNATION_RECOVERY,
            ).exclude(id__in=pre_locked_ids).update(is_locked=False, locked_reason=None)
    except _RecoveryInfeasible as exc:
        # Reached only after the atomic block above has fully rolled back.
        result = exc.result

    # Step 9: record the outcome either way. For the failure path this runs
    # in a fresh transaction, outside the one that just rolled back.
    SolverRun.objects.create(
        institution=term.institution,
        term=term,
        trigger=SolverRun.RESIGNATION_RECOVERY,
        status=SolverRun.SUCCESS if result.status == "FEASIBLE" else SolverRun.FAILED,
        objective_value=result.objective_value,
        error_message=result.error_message or "",
    )

    # Step 10.
    return result
