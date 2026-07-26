import datetime

from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    Institution,
    Subject,
    Teacher,
    TeacherSubjectEligibility,
    TimeGridConfig,
    TimetableCell,
)
from core.services.resignation import recover_from_resignation
from core.services.timegrid import generate_time_slots
from core.solver.apply import apply_solution
from core.solver.build import solve_feasibility


class ResignationTestCase(TestCase):
    """Same fixture-building style as core/tests/test_solver.py."""

    def make_institution(self, cycle_length=3):
        return Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=cycle_length
        )

    def make_grid(self, institution, periods_per_day=4, period_duration_minutes=60, breaks=None):
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

    def make_subject(self, institution, department, code):
        return Subject.objects.create(institution=institution, department=department, name=code, code=code)

    def make_teacher(self, institution, email, is_active=True, max_periods_per_day=10, max_periods_per_week=40):
        return Teacher.objects.create(
            institution=institution, name=email, email=email, is_active=is_active,
            max_periods_per_day=max_periods_per_day, max_periods_per_week=max_periods_per_week,
        )

    def make_requirement(self, institution, term, class_division, subject, periods_per_week, teacher=None):
        return CourseRequirement.objects.create(
            institution=institution, term=term, class_division=class_division, subject=subject,
            teacher=teacher, periods_per_week=periods_per_week,
        )

    def snapshot(self, term):
        """A full, order-independent snapshot of everything recover_from_resignation
        can touch, for exact before/after comparison."""
        crs = {cr.id: cr.teacher_id for cr in CourseRequirement.objects.filter(term=term)}
        cells = {
            c.id: (c.teacher_id, c.time_slot_id, c.subject_id, c.class_division_id, c.is_locked, c.locked_reason)
            for c in TimetableCell.objects.filter(term=term)
        }
        return crs, cells


class HappyPathRecoveryTests(ResignationTestCase):
    def test_resigned_teachers_requirements_move_to_a_replacement_and_others_are_untouched(self):
        institution = self.make_institution()
        self.make_grid(institution)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        resigning_teacher = self.make_teacher(institution, "resigning@test.edu", is_active=False)
        replacement_teacher = self.make_teacher(institution, "replacement@test.edu")
        subject_a = self.make_subject(institution, department, "SUBA")
        subject_b = self.make_subject(institution, department, "SUBB")
        TeacherSubjectEligibility.objects.create(institution=institution, teacher=replacement_teacher, subject=subject_a)
        TeacherSubjectEligibility.objects.create(institution=institution, teacher=replacement_teacher, subject=subject_b)
        req_a = self.make_requirement(institution, term, division, subject_a, periods_per_week=1, teacher=resigning_teacher)
        req_b = self.make_requirement(institution, term, division, subject_b, periods_per_week=1, teacher=resigning_teacher)

        # Unrelated requirement/cell that must survive byte-identical.
        unrelated_division = self.make_division(institution, department, "Div B", "B")
        unrelated_teacher = self.make_teacher(institution, "unrelated@test.edu")
        unrelated_subject = self.make_subject(institution, department, "SUBC")
        self.make_requirement(
            institution, term, unrelated_division, unrelated_subject, periods_per_week=1, teacher=unrelated_teacher
        )

        initial = solve_feasibility(term)
        self.assertEqual(initial.status, "FEASIBLE")
        apply_solution(term, initial.assignments)

        unrelated_before = TimetableCell.objects.get(term=term, subject=unrelated_subject)
        unrelated_snapshot_before = (
            unrelated_before.teacher_id, unrelated_before.time_slot_id, unrelated_before.subject_id,
        )

        result = recover_from_resignation(resigning_teacher, term)

        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(TimetableCell.objects.filter(term=term, teacher=resigning_teacher).count(), 0)

        req_a.refresh_from_db()
        req_b.refresh_from_db()
        self.assertEqual(req_a.teacher_id, replacement_teacher.id)
        self.assertEqual(req_b.teacher_id, replacement_teacher.id)

        cell_a = TimetableCell.objects.get(term=term, subject=subject_a)
        cell_b = TimetableCell.objects.get(term=term, subject=subject_b)
        self.assertEqual(cell_a.teacher_id, replacement_teacher.id)
        self.assertEqual(cell_b.teacher_id, replacement_teacher.id)

        unrelated_after = TimetableCell.objects.get(term=term, subject=unrelated_subject)
        unrelated_snapshot_after = (
            unrelated_after.teacher_id, unrelated_after.time_slot_id, unrelated_after.subject_id,
        )
        self.assertEqual(unrelated_snapshot_before, unrelated_snapshot_after)


class GenuineLockPreservedTests(ResignationTestCase):
    def test_pre_existing_locked_cell_is_completely_untouched(self):
        institution = self.make_institution()
        slots = self.make_grid(institution)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        resigning_teacher = self.make_teacher(institution, "resigning@test.edu", is_active=False)
        replacement_teacher = self.make_teacher(institution, "replacement@test.edu")
        subject = self.make_subject(institution, department, "SUBA")
        TeacherSubjectEligibility.objects.create(institution=institution, teacher=replacement_teacher, subject=subject)
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=resigning_teacher)

        pinned_division = self.make_division(institution, department, "Div B", "B")
        pinned_teacher = self.make_teacher(institution, "pinned@test.edu")
        pinned_subject = self.make_subject(institution, department, "PINNED")
        pinned_requirement = self.make_requirement(
            institution, term, pinned_division, pinned_subject, periods_per_week=1, teacher=pinned_teacher
        )
        pinned_cell = TimetableCell.objects.create(
            institution=institution, term=term, class_division=pinned_division, time_slot=slots[0],
            subject=pinned_subject, teacher=pinned_teacher, course_requirement=pinned_requirement,
            is_locked=True, locked_reason=TimetableCell.MANUAL,
        )

        result = recover_from_resignation(resigning_teacher, term)
        self.assertEqual(result.status, "FEASIBLE")

        preserved = TimetableCell.objects.get(pk=pinned_cell.pk)
        self.assertTrue(preserved.is_locked)
        self.assertEqual(preserved.locked_reason, TimetableCell.MANUAL)
        self.assertEqual(preserved.teacher_id, pinned_teacher.id)
        self.assertEqual(preserved.time_slot_id, slots[0].id)
        self.assertEqual(preserved.subject_id, pinned_subject.id)


class NoStrayLocksRemainTests(ResignationTestCase):
    def test_no_cell_is_locked_after_success_unless_it_was_genuinely_locked_before(self):
        institution = self.make_institution()
        slots = self.make_grid(institution)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        resigning_teacher = self.make_teacher(institution, "resigning@test.edu", is_active=False)
        replacement_teacher = self.make_teacher(institution, "replacement@test.edu")
        subject = self.make_subject(institution, department, "SUBA")
        TeacherSubjectEligibility.objects.create(institution=institution, teacher=replacement_teacher, subject=subject)
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=resigning_teacher)

        # Several other unlocked requirements that will get temporarily
        # locked during recovery and must end up unlocked again.
        other_teachers = [self.make_teacher(institution, f"other{i}@test.edu") for i in range(3)]
        other_subjects = [self.make_subject(institution, department, f"OTHER{i}") for i in range(3)]
        for i in range(3):
            self.make_requirement(
                institution, term, division, other_subjects[i], periods_per_week=1, teacher=other_teachers[i]
            )

        # One genuine pre-existing lock, unrelated to the resigning teacher.
        pinned_division = self.make_division(institution, department, "Div B", "B")
        pinned_teacher = self.make_teacher(institution, "pinned@test.edu")
        pinned_subject = self.make_subject(institution, department, "PINNED")
        pinned_requirement = self.make_requirement(
            institution, term, pinned_division, pinned_subject, periods_per_week=1, teacher=pinned_teacher
        )
        pinned_cell = TimetableCell.objects.create(
            institution=institution, term=term, class_division=pinned_division, time_slot=slots[0],
            subject=pinned_subject, teacher=pinned_teacher, course_requirement=pinned_requirement,
            is_locked=True, locked_reason=TimetableCell.MANUAL,
        )

        initial = solve_feasibility(term)
        self.assertEqual(initial.status, "FEASIBLE")
        apply_solution(term, initial.assignments)
        # apply_solution() only ever writes unlocked cells, so re-affirm the pin.
        pinned_cell.refresh_from_db()
        self.assertTrue(pinned_cell.is_locked)

        result = recover_from_resignation(resigning_teacher, term)
        self.assertEqual(result.status, "FEASIBLE")

        locked_cells = TimetableCell.objects.filter(term=term, is_locked=True)
        self.assertEqual(list(locked_cells.values_list("pk", flat=True)), [pinned_cell.pk])
        self.assertEqual(
            TimetableCell.objects.filter(term=term, locked_reason=TimetableCell.RESIGNATION_RECOVERY).count(), 0
        )


class InfeasibleRollbackTests(ResignationTestCase):
    def test_no_eligible_replacement_rolls_back_completely(self):
        institution = self.make_institution()
        self.make_grid(institution)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)

        resigning_teacher = self.make_teacher(institution, "resigning@test.edu", is_active=False)
        subject = self.make_subject(institution, department, "SUBA")
        # No TeacherSubjectEligibility rows for any OTHER active teacher.
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=resigning_teacher)

        unrelated_teacher = self.make_teacher(institution, "unrelated@test.edu")
        unrelated_subject = self.make_subject(institution, department, "SUBB")
        self.make_requirement(institution, term, division, unrelated_subject, periods_per_week=1, teacher=unrelated_teacher)

        initial = solve_feasibility(term)
        self.assertEqual(initial.status, "FEASIBLE")
        apply_solution(term, initial.assignments)

        before_crs, before_cells = self.snapshot(term)

        result = recover_from_resignation(resigning_teacher, term)

        self.assertNotEqual(result.status, "FEASIBLE")

        after_crs, after_cells = self.snapshot(term)
        self.assertEqual(before_crs, after_crs)
        self.assertEqual(before_cells, after_cells)
        # The resigning teacher's CourseRequirement must still point at them.
        resigning_cr = CourseRequirement.objects.get(term=term, subject=subject)
        self.assertEqual(resigning_cr.teacher_id, resigning_teacher.id)


class PreconditionTests(ResignationTestCase):
    def test_still_active_teacher_raises_and_changes_nothing(self):
        institution = self.make_institution()
        self.make_grid(institution)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = self.make_division(institution, department)
        active_teacher = self.make_teacher(institution, "active@test.edu")
        subject = self.make_subject(institution, department, "SUBA")
        self.make_requirement(institution, term, division, subject, periods_per_week=1, teacher=active_teacher)

        before_crs, before_cells = self.snapshot(term)

        with self.assertRaises(ValueError):
            recover_from_resignation(active_teacher, term)

        after_crs, after_cells = self.snapshot(term)
        self.assertEqual(before_crs, after_crs)
        self.assertEqual(before_cells, after_cells)

    def test_cross_tenant_teacher_and_term_raises(self):
        institution_a = self.make_institution()
        institution_b = self.make_institution()
        self.make_grid(institution_b)
        teacher = self.make_teacher(institution_a, "resigning@test.edu", is_active=False)
        term_b = self.make_term(institution_b)

        with self.assertRaises(ValueError):
            recover_from_resignation(teacher, term_b)
