"""
Tabilo — write a solve_feasibility()/solve_optimized() SolverResult's
assignments to TimetableCell rows.

Phase 3b re-solves the same term repeatedly as admin weight sliders get
tuned, so — unlike 3a's one-shot apply — every unlocked cell for the term
is cleared before writing the new solution. Otherwise a cell from an
earlier weight configuration that the new solve no longer produces would
just linger alongside the fresh ones. Locked cells are never touched.
"""

from django.db import transaction

from core.models import ClassDivision, CourseRequirement, Subject, Teacher, TimeSlot, TimetableCell


def apply_solution(term, assignments):
    course_requirements = CourseRequirement.objects.in_bulk({a["course_requirement_id"] for a in assignments})
    class_divisions = ClassDivision.objects.in_bulk({a["class_division_id"] for a in assignments})
    subjects = Subject.objects.in_bulk({a["subject_id"] for a in assignments})
    time_slots = TimeSlot.objects.in_bulk({a["time_slot_id"] for a in assignments})
    teachers = Teacher.objects.in_bulk({a["teacher_id"] for a in assignments})

    written = 0
    with transaction.atomic():
        # Clear stale unlocked cells first, since a rerun with different
        # weights (or updated data) can legitimately produce a different
        # layout — without this, cells from an earlier solve that the new
        # solution no longer uses would just linger alongside the new ones.
        TimetableCell.objects.filter(term=term, is_locked=False).delete()

        # Belt-and-suspenders: solve_feasibility()/solve_optimized() already
        # exclude locked cells' (class_division, time_slot) from every active
        # CR's domain, so this should never actually match — but "do not
        # touch locked cells" is a hard invariant, not an assumption.
        locked_keys = set(
            TimetableCell.objects.filter(term=term, is_locked=True).values_list(
                "class_division_id", "time_slot_id", "subject_id"
            )
        )

        for assignment in assignments:
            key = (assignment["class_division_id"], assignment["time_slot_id"], assignment["subject_id"])
            if key in locked_keys:
                continue
            course_requirement = course_requirements[assignment["course_requirement_id"]]
            # Still update_or_create (not bulk_create) for idempotency/safety
            # rather than assuming every row here is a fresh insert.
            TimetableCell.objects.update_or_create(
                term=term,
                class_division=class_divisions[assignment["class_division_id"]],
                time_slot=time_slots[assignment["time_slot_id"]],
                subject=subjects[assignment["subject_id"]],
                defaults={
                    "institution": term.institution,
                    "teacher": teachers[assignment["teacher_id"]],
                    "course_requirement": course_requirement,
                    "elective_group": course_requirement.elective_group,
                    "is_locked": False,
                },
            )
            written += 1
    return written
