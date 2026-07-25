import datetime
from collections import defaultdict

from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    ElectiveGroup,
    FacultyDutyBlock,
    Institution,
    Subject,
    Teacher,
    TeacherSubjectEligibility,
    TimeGridConfig,
    TimetableCell,
)
from core.services.timegrid import generate_time_slots
from core.solver.apply import apply_solution
from core.solver.build import solve_feasibility


class SolverTestCase(TestCase):
    """Base class with helpers for building minimal, fast, self-contained fixtures."""

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

    def make_subject(self, institution, department, code, is_elective=False):
        return Subject.objects.create(
            institution=institution, department=department, name=code, code=code, is_elective=is_elective
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


class TrivialFeasibilityTests(SolverTestCase):
    def test_trivially_feasible_case_produces_correct_cells(self):
        institution = self.make_institution(cycle_length=3)
        self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "t1@test.edu")
        self.make_requirement(institution, term, division, subject, periods_per_week=3, teacher=teacher)

        result = solve_feasibility(term)

        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(len(result.assignments), 3)

        written = apply_solution(term, result.assignments)
        self.assertEqual(written, 3)
        self.assertEqual(TimetableCell.objects.filter(term=term).count(), 3)

        slot_ids = [c.time_slot_id for c in TimetableCell.objects.filter(term=term)]
        self.assertEqual(len(slot_ids), len(set(slot_ids)))


class TeacherDoubleBookingTests(SolverTestCase):
    def test_teacher_double_booking_is_genuinely_impossible(self):
        # 2 days x 3 periods/day = 6 slots total. Two CourseRequirements share
        # one teacher and need 3 periods/week each -> exactly 6 sessions for
        # 6 slots: only feasible at all if the teacher is never double-booked.
        institution = self.make_institution(cycle_length=2)
        self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division_a = self.make_division(institution, department, "Div A")
        division_b = self.make_division(institution, department, "Div B")
        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        teacher = self.make_teacher(institution, "shared@test.edu", max_periods_per_day=3, max_periods_per_week=10)
        self.make_requirement(institution, term, division_a, subject_a, periods_per_week=3, teacher=teacher)
        self.make_requirement(institution, term, division_b, subject_b, periods_per_week=3, teacher=teacher)

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        by_teacher_slot = defaultdict(list)
        for cell in TimetableCell.objects.filter(term=term):
            by_teacher_slot[(cell.teacher_id, cell.time_slot_id)].append(cell)
        self.assertTrue(all(len(cells) == 1 for cells in by_teacher_slot.values()))
        self.assertEqual(TimetableCell.objects.filter(term=term).count(), 6)


class ClassDoubleBookingExceptElectivesTests(SolverTestCase):
    def test_ordinary_cells_never_share_a_slot_but_electives_do(self):
        institution = self.make_institution(cycle_length=3)
        self.make_grid(institution, periods_per_day=2)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        subject_c = self.make_subject(institution, department, "OEC", is_elective=True)
        subject_d = self.make_subject(institution, department, "OED", is_elective=True)
        teacher_a = self.make_teacher(institution, "ta@test.edu")
        teacher_b = self.make_teacher(institution, "tb@test.edu")
        teacher_c = self.make_teacher(institution, "tc@test.edu")
        teacher_d = self.make_teacher(institution, "td@test.edu")

        group = ElectiveGroup.objects.create(institution=institution, term=term, name="Pool")
        self.make_requirement(institution, term, division, subject_a, periods_per_week=2, teacher=teacher_a)
        self.make_requirement(institution, term, division, subject_b, periods_per_week=2, teacher=teacher_b)
        self.make_requirement(
            institution, term, division, subject_c, periods_per_week=1, teacher=teacher_c, elective_group=group
        )
        self.make_requirement(
            institution, term, division, subject_d, periods_per_week=1, teacher=teacher_d, elective_group=group
        )

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        by_class_slot = defaultdict(list)
        for cell in TimetableCell.objects.filter(term=term):
            by_class_slot[(cell.class_division_id, cell.time_slot_id)].append(cell)

        for cells in by_class_slot.values():
            if len(cells) > 1:
                elective_group_ids = {c.elective_group_id for c in cells}
                self.assertEqual(len(cells), 2)
                self.assertEqual(elective_group_ids, {group.id})

        cell_c = TimetableCell.objects.get(term=term, subject=subject_c)
        cell_d = TimetableCell.objects.get(term=term, subject=subject_d)
        self.assertEqual(cell_c.time_slot_id, cell_d.time_slot_id)


class LabContiguousBlockTests(SolverTestCase):
    def test_lab_periods_land_as_contiguous_blocks_on_distinct_days(self):
        institution = self.make_institution(cycle_length=2)
        self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "LAB1")
        teacher = self.make_teacher(institution, "lab@test.edu")
        self.make_requirement(
            institution, term, division, subject, periods_per_week=4,
            teacher=teacher, is_lab=True, block_size=2,
        )

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        cells = list(TimetableCell.objects.filter(term=term).select_related("time_slot"))
        self.assertEqual(len(cells), 4)

        by_day = defaultdict(list)
        for cell in cells:
            by_day[cell.time_slot.day_identifier].append(cell.time_slot)
        self.assertEqual(len(by_day), 2)
        for day_slots in by_day.values():
            self.assertEqual(len(day_slots), 2)
            day_slots.sort(key=lambda s: s.period_number)
            self.assertEqual(day_slots[0].end_time, day_slots[1].start_time)


class WorkloadCapTests(SolverTestCase):
    def test_workload_cap_violation_forces_infeasible(self):
        # Single day, 3 slots, one CR needing all 3 -> unavoidably 3/day for
        # its teacher. Cap the teacher at 2/day so it cannot be satisfied.
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "capped@test.edu", max_periods_per_day=2, max_periods_per_week=10)
        self.make_requirement(institution, term, division, subject, periods_per_week=3, teacher=teacher)

        result = solve_feasibility(term)
        self.assertEqual(result.status, "INFEASIBLE")
        self.assertTrue(result.error_message)


class DutyBlockExclusionTests(SolverTestCase):
    def test_duty_block_slot_is_never_used_for_that_teacher(self):
        institution = self.make_institution(cycle_length=1)
        slots = self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "duty@test.edu")
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=teacher)

        blocked_slots = slots[:2]
        for slot in blocked_slots:
            FacultyDutyBlock.objects.create(
                institution=institution, term=term, teacher=teacher, time_slot=slot,
                duty_type=FacultyDutyBlock.INVIGILATION,
            )

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        cell = TimetableCell.objects.get(term=term)
        self.assertNotIn(cell.time_slot_id, {s.id for s in blocked_slots})

        blocked_pairs = {(teacher.id, s.id) for s in blocked_slots}
        for cell in TimetableCell.objects.filter(term=term):
            self.assertNotIn((cell.teacher_id, cell.time_slot_id), blocked_pairs)


class NullTeacherEligibilityTests(SolverTestCase):
    def test_null_teacher_with_zero_eligible_teachers_returns_error_not_exception(self):
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=None)

        result = solve_feasibility(term)

        self.assertEqual(result.status, "ERROR")
        self.assertIn("SUB1", result.error_message)

    def test_null_teacher_with_eligible_teacher_is_scheduled(self):
        institution = self.make_institution(cycle_length=1)
        self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        subject = self.make_subject(institution, department, "SUB1")
        teacher = self.make_teacher(institution, "eligible@test.edu")
        TeacherSubjectEligibility.objects.create(institution=institution, teacher=teacher, subject=subject)
        self.make_requirement(institution, term, division, subject, periods_per_week=2, teacher=None)

        result = solve_feasibility(term)

        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)
        cells = TimetableCell.objects.filter(term=term)
        self.assertEqual(cells.count(), 2)
        self.assertTrue(all(c.teacher_id == teacher.id for c in cells))


class LockedCourseRequirementSkipTests(SolverTestCase):
    def test_course_requirement_with_locked_cell_is_skipped_and_preserved(self):
        institution = self.make_institution(cycle_length=1)
        slots = self.make_grid(institution, periods_per_day=3)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        locked_subject = self.make_subject(institution, department, "LOCKED")
        active_subject = self.make_subject(institution, department, "ACTIVE")
        teacher = self.make_teacher(institution, "t@test.edu")
        locked_requirement = self.make_requirement(
            institution, term, division, locked_subject, periods_per_week=1, teacher=teacher
        )
        self.make_requirement(institution, term, division, active_subject, periods_per_week=1, teacher=teacher)

        locked_cell = TimetableCell.objects.create(
            institution=institution, term=term, class_division=division, time_slot=slots[0],
            subject=locked_subject, teacher=teacher, course_requirement=locked_requirement, is_locked=True,
        )

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        self.assertTrue(all(a["course_requirement_id"] != locked_requirement.id for a in result.assignments))

        apply_solution(term, result.assignments)

        preserved = TimetableCell.objects.get(pk=locked_cell.pk)
        self.assertTrue(preserved.is_locked)
        self.assertEqual(preserved.time_slot_id, slots[0].id)

        active_cell = TimetableCell.objects.get(term=term, subject=active_subject)
        self.assertNotEqual(active_cell.time_slot_id, slots[0].id)
