"""
Tabilo — Phase 3 CP-SAT solver.

`solve_feasibility(term)` (Phase 3a): hard constraints only — every
CourseRequirement gets placed such that no class or teacher is ever
double-booked, duty blocks are respected, and workload caps hold. Any
feasible solution is accepted; no objective function.

`solve_optimized(term, weight_config=None)` (Phase 3b): the SAME hard
constraints (built by the same shared helper, not duplicated), plus a
weighted-sum quality objective — the admin "sliders" from the PRD:
  - gap minimization: penalize idle periods sandwiched between two of a
    teacher's teaching periods on the same day.
  - cognitive-load placement: penalize HIGH-priority subjects landing
    outside the first half of the day.
  - fair afternoon rotation: penalize an uneven spread of afternoon-slot
    load across teachers.
Both functions are guaranteed to report the same FEASIBLE/INFEASIBLE/ERROR
outcomes for a given term's hard constraints — 3b only changes WHICH
feasible solution is picked, never whether one exists.

Simplifying rule (still true in 3b): a CourseRequirement that already has
ANY locked TimetableCell in this term is skipped entirely (treated as
already fully satisfied) rather than rescheduled. Full partial-lock
support — locking some periods of a requirement but not others, and only
filling the rest — remains out of scope; TODO for a later phase.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from core.models import (
    CourseRequirement,
    FacultyDutyBlock,
    Subject,
    SolverWeightConfig,
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
    objective_value: float | None = None  # only set for solve_optimized() successes


@dataclass
class _ModelContext:
    """Everything a solve needs beyond the CP-SAT model itself: loaded data
    and the variable dicts _build_*() populated while adding hard
    constraints. Shared between solve_feasibility() and solve_optimized()
    so the objective-building code in 3b can reuse the exact same
    occupancy/teacher_slot_terms expressions the hard constraints use."""
    model: cp_model.CpModel
    term: object
    institution: object
    time_slots: list
    slots_by_day: dict
    requirements: list
    occupancy: dict
    teacher_choice: dict
    teacher_slot_terms: dict
    teachers_by_id: dict


def solve_feasibility(term):
    context, error_result = _build_hard_constraint_model(term)
    if error_result is not None:
        return error_result
    return _solve_and_extract(context, with_objective=False)


def solve_optimized(term, weight_config=None):
    context, error_result = _build_hard_constraint_model(term)
    if error_result is not None:
        return error_result

    if weight_config is None:
        weight_config = _resolve_weight_config(context.institution)

    _add_objective(context, weight_config)
    return _solve_and_extract(context, with_objective=True)


def _resolve_weight_config(institution):
    try:
        return institution.solver_weight_config
    except SolverWeightConfig.DoesNotExist:
        # No weights configured for this institution yet -- optimize with
        # neutral all-50s defaults (matching SolverWeightConfig's own field
        # defaults) rather than erroring.
        return SolverWeightConfig(institution=institution, gap_weight=50, cognitive_load_weight=50, fair_rotation_weight=50)


# ---------------------------------------------------------------------------
# Shared hard-constraint model construction (Phase 3a logic, unmodified)
# ---------------------------------------------------------------------------

def _build_hard_constraint_model(term):
    """
    Returns (_ModelContext, None) on success, or (None, SolverResult) if an
    unrecoverable data problem was found before any CP-SAT variables were
    created (e.g. a null-teacher CourseRequirement with zero eligible
    teachers).
    """
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
            return None, SolverResult(
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

    context = _ModelContext(
        model=model, term=term, institution=institution, time_slots=time_slots, slots_by_day=slots_by_day,
        requirements=requirements, occupancy=occupancy, teacher_choice=teacher_choice,
        teacher_slot_terms=teacher_slot_terms, teachers_by_id=teachers_by_id,
    )
    return context, None


def _solve_and_extract(context, with_objective):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT_SECONDS
    status = solver.Solve(context.model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = _extract_assignments(
            solver, context.requirements, context.time_slots, context.occupancy, context.teacher_choice
        )
        objective_value = solver.ObjectiveValue() if with_objective else None
        return SolverResult(status="FEASIBLE", assignments=assignments, objective_value=objective_value)

    if status == cp_model.INFEASIBLE:
        return SolverResult(
            status="INFEASIBLE",
            error_message=f"No feasible schedule exists for term {context.term.name} given the current constraints.",
        )

    return SolverResult(
        status="ERROR",
        error_message=(
            f"CP-SAT solve did not reach a conclusion for term {context.term.name} "
            f"(status={solver.StatusName(status)})."
        ),
    )


# ---------------------------------------------------------------------------
# Variable construction (Phase 3a logic, unmodified)
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
# Cross-CourseRequirement constraints (Phase 3a logic, unmodified)
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
# Weighted objective (Phase 3b)
# ---------------------------------------------------------------------------

def _add_objective(context, weight_config):
    model = context.model
    objective_terms = []

    gap_vars = _gap_penalty_terms(model, context.slots_by_day, context.teacher_slot_terms)
    if gap_vars:
        objective_terms.append(weight_config.gap_weight * sum(gap_vars))

    cognitive_terms = _cognitive_load_penalty_terms(context.requirements, context.slots_by_day, context.occupancy)
    if cognitive_terms:
        objective_terms.append(weight_config.cognitive_load_weight * sum(cognitive_terms))

    afternoon_slot_ids = _compute_afternoon_slot_ids(context.institution, context.slots_by_day)
    afternoon_spread = _fair_rotation_penalty_term(model, context.teacher_slot_terms, afternoon_slot_ids)
    if afternoon_spread is not None:
        objective_terms.append(weight_config.fair_rotation_weight * afternoon_spread)

    if objective_terms:
        model.Minimize(sum(objective_terms))
    # else: nothing schedulable at all (e.g. zero requirements) -- no
    # objective to set, solver just confirms the (trivially) empty solution.


def _gap_penalty_terms(model, slots_by_day, teacher_slot_terms):
    """
    One is_gap BoolVar per (teacher, day, slot index) — 1 iff that teacher
    has a teaching period earlier AND later that day, but not at this exact
    slot. A teacher with zero possible occupancy that day contributes no
    is_gap==1 vars (has_earlier/has_later chains naturally stay at 0).
    """
    gap_vars = []
    for teacher_id, slot_terms in teacher_slot_terms.items():
        for day, day_slots in slots_by_day.items():
            k = len(day_slots)
            if k < 3:
                continue  # no slot can be "sandwiched" with fewer than 3

            occupied = []
            for slot in day_slots:
                terms = slot_terms.get(slot.id)
                occupied.append(sum(terms) if terms else model.NewConstant(0))

            has_earlier = [None] * k
            has_earlier[0] = model.NewConstant(0)
            for i in range(1, k):
                var = model.NewBoolVar(f"has_earlier_t{teacher_id}_d{day}_s{i}")
                model.AddMaxEquality(var, [has_earlier[i - 1], occupied[i - 1]])
                has_earlier[i] = var

            has_later = [None] * k
            has_later[k - 1] = model.NewConstant(0)
            for i in range(k - 2, -1, -1):
                var = model.NewBoolVar(f"has_later_t{teacher_id}_d{day}_s{i}")
                model.AddMaxEquality(var, [has_later[i + 1], occupied[i + 1]])
                has_later[i] = var

            for i in range(k):
                is_gap = model.NewBoolVar(f"is_gap_t{teacher_id}_d{day}_s{i}")
                model.Add(is_gap <= has_earlier[i])
                model.Add(is_gap <= has_later[i])
                model.Add(is_gap <= 1 - occupied[i])
                model.Add(is_gap >= has_earlier[i] + has_later[i] + (1 - occupied[i]) - 2)
                gap_vars.append(is_gap)

    return gap_vars


def _cognitive_load_penalty_terms(requirements, slots_by_day, occupancy):
    """
    Penalize a HIGH cognitive_load_priority subject's occupancy at any slot
    outside its day's "preferred window" — the first ceil(k/2) of that
    day's ordered non-break slots. Reuses the existing occupancy
    expressions directly; no new variables needed.
    """
    non_preferred_slot_ids = set()
    for day_slots in slots_by_day.values():
        preferred_count = math.ceil(len(day_slots) / 2)
        non_preferred_slot_ids.update(s.id for s in day_slots[preferred_count:])

    terms = []
    for cr in requirements:
        if cr.subject.cognitive_load_priority != Subject.HIGH:
            continue
        for slot_id, expr in occupancy[cr.id].items():
            if slot_id in non_preferred_slot_ids:
                terms.append(expr)
    return terms


def _compute_afternoon_slot_ids(institution, slots_by_day):
    """
    "Afternoon" = any slot whose period_number is greater than the highest
    period_number covered by that day's breaks. A day with no break at all
    has no "afternoon" by this definition (nothing marks its midpoint).
    """
    max_break_period_by_day = {}
    for slot in TimeSlot.objects.filter(institution=institution, is_break=True):
        max_break_period_by_day[slot.day_identifier] = max(
            max_break_period_by_day.get(slot.day_identifier, 0), slot.period_number
        )

    afternoon_slot_ids = set()
    for day, day_slots in slots_by_day.items():
        max_break_period = max_break_period_by_day.get(day)
        if max_break_period is None:
            continue
        afternoon_slot_ids.update(s.id for s in day_slots if s.period_number > max_break_period)
    return afternoon_slot_ids


def _fair_rotation_penalty_term(model, teacher_slot_terms, afternoon_slot_ids):
    """
    max(afternoon_count) - min(afternoon_count) across every teacher with
    at least one assignment anywhere in the term (i.e. every teacher present
    in teacher_slot_terms — any CR referencing them must reach its full
    periods_per_week in any feasible solution).
    """
    if not teacher_slot_terms:
        return None

    upper_bound = max(len(afternoon_slot_ids), 1)
    afternoon_counts = []
    for teacher_id, slot_terms in teacher_slot_terms.items():
        afternoon_terms = [
            term for slot_id in afternoon_slot_ids for term in slot_terms.get(slot_id, [])
        ]
        count_var = model.NewIntVar(0, upper_bound, f"afternoon_count_t{teacher_id}")
        model.Add(count_var == (sum(afternoon_terms) if afternoon_terms else 0))
        afternoon_counts.append(count_var)

    max_afternoon = model.NewIntVar(0, upper_bound, "max_afternoon")
    min_afternoon = model.NewIntVar(0, upper_bound, "min_afternoon")
    model.AddMaxEquality(max_afternoon, afternoon_counts)
    model.AddMinEquality(min_afternoon, afternoon_counts)

    spread = model.NewIntVar(0, upper_bound, "afternoon_spread")
    model.Add(spread == max_afternoon - min_afternoon)
    return spread


# ---------------------------------------------------------------------------
# Solution extraction (Phase 3a logic, unmodified)
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
