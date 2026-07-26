import datetime

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    Department,
    ElectiveGroup,
    Institution,
    Subject,
    Teacher,
    TimeSlot,
    TimetableCell,
)


class TimetableCellEnforcesElectiveAwareUniquenessTests(TestCase):
    """
    Regression coverage for the Phase 1 bug: unique_together on
    (term, class_division, time_slot) couldn't tell an accidental
    double-booking apart from intentional elective parallelism (e.g.
    OE501A / OE501B sharing a class_division + time_slot).
    """

    def setUp(self):
        self.college = Institution.objects.create(
            name="Coromandel Institute of Engineering", institution_type=Institution.COLLEGE, cycle_length=6
        )
        self.department = Department.objects.create(institution=self.college, name="Computer Science")
        self.term = AcademicTerm.objects.create(
            institution=self.college, name="Odd Semester 2026-27",
            start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2026, 11, 30),
        )
        self.division = ClassDivision.objects.create(
            institution=self.college, department=self.department, name="B.Tech CSE III Year", section="A"
        )
        self.time_slot = TimeSlot.objects.create(
            institution=self.college, day_identifier=1, period_number=1,
            start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
        )
        self.teacher_a = Teacher.objects.create(
            institution=self.college, name="Dr. Kavitha Shankar", email="kavitha@coromandel.edu",
            max_periods_per_day=5, max_periods_per_week=24,
        )
        self.teacher_b = Teacher.objects.create(
            institution=self.college, name="Prof. Vignesh Raghavan", email="vignesh@coromandel.edu",
            max_periods_per_day=5, max_periods_per_week=24,
        )
        self.subject_a = Subject.objects.create(
            institution=self.college, department=self.department, name="Open Elective - AI Basics",
            code="OE501A", is_elective=True,
        )
        self.subject_b = Subject.objects.create(
            institution=self.college, department=self.department, name="Open Elective - Robotics",
            code="OE501B", is_elective=True,
        )
        self.elective_group = ElectiveGroup.objects.create(
            institution=self.college, term=self.term, name="Open Elective Pool - Sem 5"
        )

    def test_ordinary_double_booking_of_a_class_is_rejected(self):
        TimetableCell.objects.create(
            institution=self.college, term=self.term, class_division=self.division, time_slot=self.time_slot,
            subject=self.subject_a, teacher=self.teacher_a,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TimetableCell.objects.create(
                    institution=self.college, term=self.term, class_division=self.division,
                    time_slot=self.time_slot, subject=self.subject_b, teacher=self.teacher_b,
                )

    def test_parallel_elective_sections_can_share_class_and_slot(self):
        TimetableCell.objects.create(
            institution=self.college, term=self.term, class_division=self.division, time_slot=self.time_slot,
            subject=self.subject_a, teacher=self.teacher_a, elective_group=self.elective_group,
        )
        # Must NOT raise: two elective sections sharing (term, class_division, time_slot).
        TimetableCell.objects.create(
            institution=self.college, term=self.term, class_division=self.division, time_slot=self.time_slot,
            subject=self.subject_b, teacher=self.teacher_b, elective_group=self.elective_group,
        )
        self.assertEqual(
            TimetableCell.objects.filter(
                term=self.term, class_division=self.division, time_slot=self.time_slot
            ).count(),
            2,
        )

    def test_duplicate_elective_cell_for_same_subject_is_still_rejected(self):
        TimetableCell.objects.create(
            institution=self.college, term=self.term, class_division=self.division, time_slot=self.time_slot,
            subject=self.subject_a, teacher=self.teacher_a, elective_group=self.elective_group,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TimetableCell.objects.create(
                    institution=self.college, term=self.term, class_division=self.division,
                    time_slot=self.time_slot, subject=self.subject_a, teacher=self.teacher_b,
                    elective_group=self.elective_group,
                )

    def test_teacher_double_booking_still_rejected_even_across_elective_groups(self):
        other_division = ClassDivision.objects.create(
            institution=self.college, department=self.department, name="B.Tech CSE III Year", section="B"
        )
        TimetableCell.objects.create(
            institution=self.college, term=self.term, class_division=self.division, time_slot=self.time_slot,
            subject=self.subject_a, teacher=self.teacher_a, elective_group=self.elective_group,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TimetableCell.objects.create(
                    institution=self.college, term=self.term, class_division=other_division,
                    time_slot=self.time_slot, subject=self.subject_b, teacher=self.teacher_a,
                    elective_group=self.elective_group,
                )
