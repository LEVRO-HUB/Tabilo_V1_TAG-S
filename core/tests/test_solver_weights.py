import datetime
from collections import defaultdict

from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    Institution,
    Subject,
    SolverWeightConfig,
    Teacher,
    TimeGridConfig,
    TimetableCell,
)
from core.services.timegrid import generate_time_slots
from core.solver.apply import apply_solution
from core.solver.build import solve_feasibility, solve_optimized


class SolverTestCase(TestCase):
    """Same fixture-building style as core/tests/test_solver.py."""

    def make_institution(self, cycle_length):
        return Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=cycle_length
        )

    def make_grid(self, institution, periods_per_day, period_duration_minutes=60, breaks=None):
        TimeGridConfig.objects.create(
            institution=institution,
            periods_per_day=periods_per_day,
            period_duration_minutes=period_duration_minutes,
            day_start_time=datetime.time(9, 0),
            breaks=breaks or [],
        )
        return generate_time_slots(institution)

    def make_term(self, institution, name="Term"):
        return AcademicTerm.objects.create(
            institution=institution, name=name,
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 3, 31),
        )

    def make_division(self, institution, department, name="Div A", section="A"):
        return ClassDivision.objects.create(institution=institution, department=department, name=name, section=section)

    def make_subject(self, institution, department, code, is_elective=False, cognitive_load_priority=Subject.NORMAL):
        return Subject.objects.create(
            institution=institution, department=department, name=code, code=code, is_elective=is_elective,
            cognitive_load_priority=cognitive_load_priority,
        )

    def make_teacher(self, institution, email, max_periods_per_day=10, max_periods_per_week=40):
        return Teacher.objects.create(
            institution=institution, name=email, email=email,
            max_periods_per_day=max_periods_per_day, max_periods_per_week=max_periods_per_week,
        )

    def make_requirement(
        self, institution, term, class_division, subject, periods_per_week,
        teacher=None, is_lab=False, block_size=1, elective_group=None,
    ):
        return CourseRequirement.objects.create(
            institution=institution, term=term, class_division=class_division, subject=subject,
            teacher=teacher, periods_per_week=periods_per_week, is_lab=is_lab, block_size=block_size,
            elective_group=elective_group,
        )


class GapMinimizationTests(SolverTestCase):
    def test_optimized_solve_prefers_gap_free_layout(self):
        # 1 day, 5 slots, 1 teacher needing exactly 2 single-period sessions.
        # Plenty of layouts are hard-constraint-feasible (any 2 distinct
        # slots); only some are gap-free (the two sessions adjacent). With
        # gap_weight dominant, solve_optimized() must pick an adjacent one.
        # solve_feasibility() is deliberately not exercised here -- it has
        # no reason to avoid a gap and isn't asserted either way.
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=5)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        teacher = self.make_teacher(institution, "t@test.edu", max_periods_per_day=5, max_periods_per_week=20)
        self.make_requirement(institution, term, division, subject_a, periods_per_week=1, teacher=teacher)
        self.make_requirement(institution, term, division, subject_b, periods_per_week=1, teacher=teacher)

        weights = SolverWeightConfig(gap_weight=100, cognitive_load_weight=0, fair_rotation_weight=0)
        result = solve_optimized(term, weight_config=weights)

        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        cells = list(TimetableCell.objects.filter(term=term, teacher=teacher).select_related("time_slot"))
        self.assertEqual(len(cells), 2)
        periods = sorted(c.time_slot.period_number for c in cells)
        self.assertEqual(periods[1] - periods[0], 1, "expected the two sessions to land on adjacent periods")


class CognitiveLoadPlacementTests(SolverTestCase):
    def test_high_priority_subject_lands_in_preferred_window(self):
        # 1 day, 4 slots -> preferred window = first ceil(4/2)=2 periods.
        # Nothing else constrains where the single session can go, so with
        # cognitive_load_weight dominant it must land in periods 1-2.
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "HARD1", cognitive_load_priority=Subject.HIGH)
        teacher = self.make_teacher(institution, "t@test.edu")
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=teacher)

        weights = SolverWeightConfig(gap_weight=0, cognitive_load_weight=100, fair_rotation_weight=0)
        result = solve_optimized(term, weight_config=weights)

        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        cell = TimetableCell.objects.get(term=term, subject=subject)
        self.assertLessEqual(cell.time_slot.period_number, 2)


class FairAfternoonRotationTests(SolverTestCase):
    def test_high_fair_rotation_weight_reduces_afternoon_spread(self):
        # 1 day, 6 teaching periods with a break after period 3 -> non-break
        # period_numbers [1,2,3,5,6,7], "afternoon" = period_number > 3, i.e.
        # {5,6,7} (3 slots). Two *different* class_divisions with *different*
        # teachers means their slot choices don't compete at all (no shared
        # class or teacher clash), so both CRs are individually free to place
        # sessions in the afternoon or not -- a perfectly even split (both
        # teachers at the same afternoon count) is achievable, and an uneven
        # one is equally hard-constraint-valid with no fairness pressure.
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=6, breaks=[{"after_period": 3, "duration_minutes": 60}])
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division_a = self.make_division(institution, department, "Div A")
        division_b = self.make_division(institution, department, "Div B")
        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        teacher_a = self.make_teacher(institution, "ta@test.edu", max_periods_per_day=6, max_periods_per_week=20)
        teacher_b = self.make_teacher(institution, "tb@test.edu", max_periods_per_day=6, max_periods_per_week=20)
        self.make_requirement(institution, term, division_a, subject_a, periods_per_week=4, teacher=teacher_a)
        self.make_requirement(institution, term, division_b, subject_b, periods_per_week=2, teacher=teacher_b)

        def afternoon_spread(weight_config):
            result = solve_optimized(term, weight_config=weight_config)
            self.assertEqual(result.status, "FEASIBLE")
            counts = defaultdict(int)
            for a in result.assignments:
                slot = next(s for s in generate_time_slots(institution) if s.id == a["time_slot_id"])
                if slot.period_number > 3:
                    counts[a["teacher_id"]] += 1
            values = [counts.get(teacher_a.id, 0), counts.get(teacher_b.id, 0)]
            return max(values) - min(values)

        fair_weights = SolverWeightConfig(gap_weight=0, cognitive_load_weight=0, fair_rotation_weight=100)
        unfair_weights = SolverWeightConfig(gap_weight=0, cognitive_load_weight=0, fair_rotation_weight=0)

        fair_spread = afternoon_spread(fair_weights)
        unfair_spread = afternoon_spread(unfair_weights)

        self.assertEqual(fair_spread, 0)
        self.assertLess(fair_spread, unfair_spread)


class DefaultWeightFallbackTests(SolverTestCase):
    def test_solve_optimized_without_weight_config_row_falls_back_to_defaults(self):
        institution = self.make_institution(cycle_length=3)
        self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "t@test.edu")
        self.make_requirement(institution, term, division, subject, periods_per_week=2, teacher=teacher)

        # No weight_config passed AND no SolverWeightConfig row exists.
        result = solve_optimized(term)

        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(len(result.assignments), 2)


class ObjectiveValueTests(SolverTestCase):
    def test_objective_value_set_for_optimized_and_none_for_feasibility_only(self):
        institution = self.make_institution(cycle_length=3)
        self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "t@test.edu")
        self.make_requirement(institution, term, division, subject, periods_per_week=2, teacher=teacher)

        weights = SolverWeightConfig(gap_weight=10, cognitive_load_weight=10, fair_rotation_weight=10)
        optimized_result = solve_optimized(term, weight_config=weights)
        self.assertEqual(optimized_result.status, "FEASIBLE")
        self.assertIsNotNone(optimized_result.objective_value)

        feasibility_result = solve_feasibility(term)
        self.assertEqual(feasibility_result.status, "FEASIBLE")
        self.assertIsNone(feasibility_result.objective_value)


class ApplySolutionStaleCellCleanupTests(SolverTestCase):
    def test_apply_solution_clears_stale_unlocked_cells_between_runs(self):
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=5)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        teacher = self.make_teacher(institution, "t@test.edu", max_periods_per_day=5, max_periods_per_week=20)
        self.make_requirement(institution, term, division, subject_a, periods_per_week=1, teacher=teacher)
        self.make_requirement(institution, term, division, subject_b, periods_per_week=1, teacher=teacher)

        neutral_weights = SolverWeightConfig(gap_weight=0, cognitive_load_weight=0, fair_rotation_weight=0)
        first_result = solve_optimized(term, weight_config=neutral_weights)
        self.assertEqual(first_result.status, "FEASIBLE")
        apply_solution(term, first_result.assignments)

        first_cells = list(TimetableCell.objects.filter(term=term))
        self.assertEqual(len(first_cells), 2)
        first_cell_ids = {c.id for c in first_cells}

        gap_averse_weights = SolverWeightConfig(gap_weight=100, cognitive_load_weight=0, fair_rotation_weight=0)
        second_result = solve_optimized(term, weight_config=gap_averse_weights)
        self.assertEqual(second_result.status, "FEASIBLE")
        apply_solution(term, second_result.assignments)

        second_cells = list(TimetableCell.objects.filter(term=term))
        self.assertEqual(len(second_cells), 2)
        second_cell_ids = {c.id for c in second_cells}

        # apply_solution() deletes every unlocked cell before rewriting, so
        # rows are always fresh inserts on a rerun -- even if the new solve
        # happened to land on the same slots, these are new primary keys,
        # proving the old rows were genuinely cleared rather than reused.
        self.assertEqual(first_cell_ids & second_cell_ids, set())

    def test_apply_solution_never_touches_locked_cells_across_runs(self):
        institution = self.make_institution(cycle_length=1)
        slots = self.make_grid(institution, periods_per_day=5)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        locked_subject = self.make_subject(institution, department, "LOCKED")
        active_subject = self.make_subject(institution, department, "ACTIVE")
        teacher = self.make_teacher(institution, "t2@test.edu", max_periods_per_day=5, max_periods_per_week=20)
        locked_requirement = self.make_requirement(
            institution, term, division, locked_subject, periods_per_week=1, teacher=teacher
        )
        self.make_requirement(institution, term, division, active_subject, periods_per_week=1, teacher=teacher)
        locked_cell = TimetableCell.objects.create(
            institution=institution, term=term, class_division=division, time_slot=slots[0],
            subject=locked_subject, teacher=teacher, course_requirement=locked_requirement, is_locked=True,
        )

        result = solve_optimized(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        preserved = TimetableCell.objects.get(pk=locked_cell.pk)
        self.assertTrue(preserved.is_locked)
        self.assertEqual(preserved.time_slot_id, slots[0].id)
