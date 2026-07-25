"""
Tabilo — Phase 3a CP-SAT feasibility solver.

Builds and solves a hard-constraints-only CP-SAT model for one AcademicTerm:
every CourseRequirement gets placed into TimeSlots such that no class or
teacher is ever double-booked, duty blocks are respected, and workload caps
hold. There is no objective function in this phase (no gap minimization,
cognitive load, or fair rotation) — any feasible solution is accepted.
That's Phase 3b.

Simplifying rule for 3a: a CourseRequirement that already has ANY locked
TimetableCell in this term is skipped entirely (treated as already fully
satisfied) rather than rescheduled. Full partial-lock support — locking
some periods of a requirement but not others, and only filling the rest —
is out of scope for 3a; TODO for a later phase.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from core.models import (
    CourseRequirement,
    FacultyDutyBlock,
    Teacher,
    TeacherSubjectEligibility,
    TimeSlot,
    TimetableCell,
)

SOLVER_TIME_LIMIT_SECONDS = 30


@dataclass
class SolverResult:
    status: str  # "FEASIBLE" / "INFEASIBLE" / "ERROR"
    assignments: list = field(default_factory=list)
    error_message: str | None = None


def solve_feasibility(term):
    institution = term.institution

    time_slots = list(
        TimeSlot.objects.filter(institution=institution, is_break=False)
        .order_by("day_identifier", "period_number")
    )
    slots_by_day = defaultdict(list)
    for slot in time_slots:
        slots_by_day[slot.day_identifier].append(slot)

    locked_cells = list(TimetableCell.objects.filter(term=term, is_locked=True))
    locked_cr_ids = {cell.course_requirement_id for cell in locked_cells if cell.course_requirement_id}
    # Occupied by a cell we must never touch or collide with this run, even
    # though the CourseRequirement that produced it isn't being rescheduled.
    forbidden_class_slot_pairs = {(cell.class_division_id, cell.time_slot_id) for cell in locked_cells}
    locked_teacher_slot_pairs = {(cell.teacher_id, cell.time_slot_id) for cell in locked_cells}

    requirements = list(
        CourseRequirement.objects.filter(term=term)
        .exclude(id__in=locked_cr_ids)
        .select_related("subject", "class_division", "teacher", "elective_group")
    )

    duty_block_pairs = set(
        FacultyDutyBlock.objects.filter(term=term).values_list("teacher_id", "time_slot_id")
    )
    forbidden_teacher_slot_pairs = duty_block_pairs | locked_teacher_slot_pairs

    eligible_teachers_by_subject = defaultdict(list)
    for teacher_id, subject_id in TeacherSubjectEligibility.objects.filter(
        institution=institution
    ).values_list("teacher_id", "subject_id"):
        eligible_teachers_by_subject[subject_id].append(teacher_id)

    for cr in requirements:
        if cr.teacher_id is None and not eligible_teachers_by_subject.get(cr.subject_id):
            return SolverResult(
                status="ERROR",
                error_message=(
                    f"CourseRequirement {cr.id} ({cr.class_division} — {cr.subject}) has no assigned "
                    f"teacher and no TeacherSubjectEligibility rows exist for subject {cr.subject}."
                ),
            )

    teachers_by_id = {t.id: t for t in Teacher.objects.filter(institution=institution)}

    model = cp_model.CpModel()

    occupancy = defaultdict(dict)  # occupancy[cr.id][slot.id] -> BoolVar or LinearExpr, 0/1-valued
    teacher_choice = defaultdict(dict)  # teacher_choice[cr.id][teacher_id] -> BoolVar (null-teacher CRs only)
    teacher_slot_terms = defaultdict(lambda: defaultdict(list))  # [teacher_id][slot.id] -> list of expr

    for cr in requirements:
        if cr.block_size <= 1:
            _build_non_lab(
                model, cr, time_slots, slots_by_day, institution.cycle_length,
                forbidden_class_slot_pairs, forbidden_teacher_slot_pairs,
                eligible_teachers_by_subject, occupancy, teacher_choice, teacher_slot_terms,
            )
        else:
            _build_lab(
                model, cr, slots_by_day,
                forbidden_class_slot_pairs, forbidden_teacher_slot_pairs,
                eligible_teachers_by_subject, occupancy, teacher_choice, teacher_slot_terms,
            )

    _link_elective_groups(model, requirements, time_slots, occupancy)
    _add_class_double_booking_constraints(model, requirements, time_slots, occupancy)
    _add_teacher_constraints(model, teacher_slot_terms, slots_by_day, teachers_by_id)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = _extract_assignments(solver, requirements, time_slots, occupancy, teacher_choice)
        return SolverResult(status="FEASIBLE", assignments=assignments)

    if status == cp_model.INFEASIBLE:
        return SolverResult(
            status="INFEASIBLE",
            error_message=f"No feasible schedule exists for term {term.name} given the current constraints.",
        )

    return SolverResult(
        status="ERROR",
        error_message=f"CP-SAT solve did not reach a conclusion for term {term.name} (status={solver.StatusName(status)}).",
    )


# ---------------------------------------------------------------------------
# Variable construction
# ---------------------------------------------------------------------------

def _build_non_lab(
    model, cr, time_slots, slots_by_day, cycle_length,
    forbidden_class_slot_pairs, forbidden_teacher_slot_pairs,
    eligible_teachers_by_subject, occupancy, teacher_choice, teacher_slot_terms,
):
    for slot in time_slots:
        if (cr.class_division_id, slot.id) in forbidden_class_slot_pairs:
            continue
        if cr.teacher_id is not None and (cr.teacher_id, slot.id) in forbidden_teacher_slot_pairs:
            continue
        occupancy[cr.id][slot.id] = model.NewBoolVar(f"x_cr{cr.id}_slot{slot.id}")

    model.Add(sum(occupancy[cr.id].values()) == cr.periods_per_week)

    if cr.periods_per_week <= cycle_length:
        for day, day_slots in slots_by_day.items():
            day_vars = [occupancy[cr.id][s.id] for s in day_slots if s.id in occupancy[cr.id]]
            if day_vars:
                model.Add(sum(day_vars) <= 1)
    # else: periods_per_week exceeds cycle_length, so the subject MUST repeat
    # on some day at least once — an "at most 1/day" cap would make this CR
    # unschedulable no matter what, so it's intentionally not enforced.

    _link_teacher(model, cr, time_slots, forbidden_teacher_slot_pairs, eligible_teachers_by_subject,
                  occupancy, teacher_choice, teacher_slot_terms)


def _build_lab(
    model, cr, slots_by_day,
    forbidden_class_slot_pairs, forbidden_teacher_slot_pairs,
    eligible_teachers_by_subject, occupancy, teacher_choice, teacher_slot_terms,
):
    block_size = cr.block_size
    window_vars_by_day = defaultdict(list)
    windows_covering_slot = defaultdict(list)  # slot.id -> list of window BoolVars

    for day, day_slots in slots_by_day.items():
        for window in _contiguous_windows(day_slots, block_size):
            if any((cr.class_division_id, s.id) in forbidden_class_slot_pairs for s in window):
                continue
            if cr.teacher_id is not None and any(
                (cr.teacher_id, s.id) in forbidden_teacher_slot_pairs for s in window
            ):
                continue
            window_var = model.NewBoolVar(
                f"w_cr{cr.id}_day{day}_start{window[0].id}"
            )
            window_vars_by_day[day].append(window_var)
            for s in window:
                windows_covering_slot[s.id].append(window_var)

    for slot_id, covering_vars in windows_covering_slot.items():
        occupancy[cr.id][slot_id] = sum(covering_vars)

    all_window_vars = [v for vars_ in window_vars_by_day.values() for v in vars_]
    model.Add(sum(all_window_vars) == cr.periods_per_week // block_size)

    for day_vars in window_vars_by_day.values():
        model.Add(sum(day_vars) <= 1)

    # occupancy[cr.id][slot] is a sum of window vars covering that slot; the
    # "at most one window per day" constraint above guarantees it's always
    # 0 or 1 in any solution, so it can be used directly wherever a 0/1
    # occupancy expression is needed (no separate boolean required).
    all_slots = [s for day_slots in slots_by_day.values() for s in day_slots]
    _link_teacher(model, cr, all_slots, forbidden_teacher_slot_pairs, eligible_teachers_by_subject,
                  occupancy, teacher_choice, teacher_slot_terms)


def _contiguous_windows(day_slots, block_size):
    """
    All windows of exactly `block_size` consecutive, truly time-contiguous
    slots within a single day's non-break slots. period_number adjacency
    alone is NOT sufficient — a break slot in between breaks contiguity even
    though period_numbers stay sequential, so this checks actual
    end_time == next.start_time.
    """
    windows = []
    n = len(day_slots)
    for start in range(n):
        window = [day_slots[start]]
        for i in range(start + 1, start + block_size):
            if i >= n or day_slots[i - 1].end_time != day_slots[i].start_time:
                break
            window.append(day_slots[i])
        if len(window) == block_size:
            windows.append(window)
    return windows


def _link_teacher(
    model, cr, candidate_slots, forbidden_teacher_slot_pairs, eligible_teachers_by_subject,
    occupancy, teacher_choice, teacher_slot_terms,
):
    if cr.teacher_id is not None:
        # Fixed teacher: occupancy vars were already excluded above wherever
        # (teacher, slot) was forbidden, so occupancy IS teacher-occupancy.
        for slot in candidate_slots:
            expr = occupancy[cr.id].get(slot.id)
            if expr is not None:
                teacher_slot_terms[cr.teacher_id][slot.id].append(expr)
        return

    eligible = eligible_teachers_by_subject[cr.subject_id]
    for teacher_id in eligible:
        teacher_choice[cr.id][teacher_id] = model.NewBoolVar(f"t_cr{cr.id}_teacher{teacher_id}")
    model.Add(sum(teacher_choice[cr.id].values()) == 1)

    for slot in candidate_slots:
        occupancy_expr = occupancy[cr.id].get(slot.id)
        if occupancy_expr is None:
            continue
        for teacher_id in eligible:
            choice_var = teacher_choice[cr.id][teacher_id]
            if (teacher_id, slot.id) in forbidden_teacher_slot_pairs:
                # Don't create a reified var for a forbidden pair — just
                # forbid the combination directly (occupancy_expr is 0/1).
                model.Add(occupancy_expr + choice_var <= 1)
                continue
            y = model.NewBoolVar(f"y_cr{cr.id}_teacher{teacher_id}_slot{slot.id}")
            model.Add(y <= occupancy_expr)
            model.Add(y <= choice_var)
            model.Add(y >= occupancy_expr + choice_var - 1)
            teacher_slot_terms[teacher_id][slot.id].append(y)


# ---------------------------------------------------------------------------
# Cross-CourseRequirement constraints
# ---------------------------------------------------------------------------

def _link_elective_groups(model, requirements, time_slots, occupancy):
    by_group = defaultdict(list)
    for cr in requirements:
        if cr.elective_group_id is not None:
            by_group[cr.elective_group_id].append(cr)

    for group_crs in by_group.values():
        if len(group_crs) < 2:
            continue
        reference, others = group_crs[0], group_crs[1:]
        for other in others:
            for slot in time_slots:
                ref_expr = occupancy[reference.id].get(slot.id)
                other_expr = occupancy[other.id].get(slot.id)
                if ref_expr is None and other_expr is None:
                    continue
                if ref_expr is None or other_expr is None:
                    # One member structurally can't occupy this slot (e.g. its
                    # fixed teacher is duty-blocked here) — the whole group,
                    # being forced simultaneous, can't use this slot either.
                    if ref_expr is not None:
                        model.Add(ref_expr == 0)
                    if other_expr is not None:
                        model.Add(other_expr == 0)
                    continue
                model.Add(ref_expr == other_expr)


def _add_class_double_booking_constraints(model, requirements, time_slots, occupancy):
    by_class_division = defaultdict(list)
    for cr in requirements:
        by_class_division[cr.class_division_id].append(cr)

    for crs in by_class_division.values():
        for slot in time_slots:
            terms = []
            seen_groups = set()
            for cr in crs:
                expr = occupancy[cr.id].get(slot.id)
                if expr is None:
                    continue
                group_id = cr.elective_group_id
                if group_id is not None:
                    if group_id in seen_groups:
                        # Already counted one representative for this group;
                        # the rest are structurally forced equal to it.
                        continue
                    seen_groups.add(group_id)
                terms.append(expr)
            if terms:
                model.Add(sum(terms) <= 1)


def _add_teacher_constraints(model, teacher_slot_terms, slots_by_day, teachers_by_id):
    for teacher_id, slot_terms in teacher_slot_terms.items():
        for terms in slot_terms.values():
            model.Add(sum(terms) <= 1)

        teacher = teachers_by_id[teacher_id]
        week_terms = []
        for day_slots in slots_by_day.values():
            day_terms = [
                term for s in day_slots for term in slot_terms.get(s.id, [])
            ]
            if day_terms:
                model.Add(sum(day_terms) <= teacher.max_periods_per_day)
            week_terms.extend(day_terms)
        if week_terms:
            model.Add(sum(week_terms) <= teacher.max_periods_per_week)


# ---------------------------------------------------------------------------
# Solution extraction
# ---------------------------------------------------------------------------

def _extract_assignments(solver, requirements, time_slots, occupancy, teacher_choice):
    assignments = []
    for cr in requirements:
        if cr.teacher_id is not None:
            chosen_teacher_id = cr.teacher_id
        else:
            chosen_teacher_id = next(
                teacher_id for teacher_id, var in teacher_choice[cr.id].items()
                if solver.Value(var) == 1
            )
        for slot in time_slots:
            expr = occupancy[cr.id].get(slot.id)
            if expr is not None and solver.Value(expr) == 1:
                assignments.append({
                    "course_requirement_id": cr.id,
                    "class_division_id": cr.class_division_id,
                    "subject_id": cr.subject_id,
                    "time_slot_id": slot.id,
                    "teacher_id": chosen_teacher_id,
                })
    return assignments
