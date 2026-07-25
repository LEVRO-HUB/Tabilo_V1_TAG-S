import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    Department,
    Institution,
    Subject,
    Teacher,
    TimeGridConfig,
    TimeSlot,
    TimetableCell,
)
from core.services.timegrid import generate_time_slots


class GenerateTimeSlotsTests(TestCase):
    def setUp(self):
        self.institution = Institution.objects.create(
            name="Greenwood Public School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        self.config = TimeGridConfig.objects.create(
            institution=self.institution,
            periods_per_day=6,
            period_duration_minutes=45,
            day_start_time=datetime.time(9, 0),
            breaks=[{"after_period": 4, "duration_minutes": 30}],
        )

    def test_missing_config_raises(self):
        bare_institution = Institution.objects.create(name="No Config Co", institution_type=Institution.SCHOOL)
        with self.assertRaises(ValidationError):
            generate_time_slots(bare_institution)

    def test_generates_one_slot_row_per_period_including_breaks(self):
        slots = generate_time_slots(self.institution)
        # 6 days x (6 teaching periods + 1 break) = 42 rows.
        self.assertEqual(len(slots), 42)
        self.assertEqual(TimeSlot.objects.filter(institution=self.institution).count(), 42)

        day1 = TimeSlot.objects.filter(institution=self.institution, day_identifier=1).order_by("period_number")
        self.assertEqual([s.period_number for s in day1], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([s.is_break for s in day1], [False, False, False, False, True, False, False])

        break_slot = day1.get(period_number=5)
        self.assertEqual(break_slot.start_time, datetime.time(12, 0))
        self.assertEqual(break_slot.end_time, datetime.time(12, 30))

        last_slot = day1.get(period_number=7)
        self.assertEqual(last_slot.start_time, datetime.time(13, 15))
        self.assertEqual(last_slot.end_time, datetime.time(14, 0))

    def test_idempotent_without_regenerate(self):
        generate_time_slots(self.institution)
        result = generate_time_slots(self.institution)
        self.assertEqual(len(result), 42)
        self.assertEqual(TimeSlot.objects.filter(institution=self.institution).count(), 42)

    def test_regenerate_rebuilds_from_updated_config(self):
        generate_time_slots(self.institution)
        self.config.period_duration_minutes = 60
        self.config.save()

        result = generate_time_slots(self.institution, regenerate=True)
        self.assertEqual(len(result), 42)
        first_period = TimeSlot.objects.get(institution=self.institution, day_identifier=1, period_number=1)
        self.assertEqual(first_period.end_time, datetime.time(10, 0))

    def test_regenerate_refuses_when_timetable_cells_reference_existing_slots(self):
        generate_time_slots(self.institution)

        department = Department.objects.get(institution=self.institution, name="General")
        term = AcademicTerm.objects.create(
            institution=self.institution, name="Term 1",
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 3, 31),
        )
        division = ClassDivision.objects.create(
            institution=self.institution, department=department, name="Grade 8", section="A"
        )
        subject = Subject.objects.create(
            institution=self.institution, department=department, name="Mathematics", code="MATH8"
        )
        teacher = Teacher.objects.create(
            institution=self.institution, name="Anita Raman", email="anita@greenwood.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        occupied_slot = TimeSlot.objects.filter(institution=self.institution, is_break=False).first()
        cell = TimetableCell.objects.create(
            institution=self.institution, term=term, class_division=division,
            time_slot=occupied_slot, subject=subject, teacher=teacher,
        )

        with self.assertRaises(ValidationError):
            generate_time_slots(self.institution, regenerate=True)

        # Existing slots (and the cell pointing at one of them) must survive untouched.
        self.assertEqual(TimeSlot.objects.filter(institution=self.institution).count(), 42)
        self.assertTrue(TimetableCell.objects.filter(pk=cell.pk).exists())

    def test_invalid_break_configuration_raises(self):
        self.config.breaks = [{"after_period": 99, "duration_minutes": 30}]
        self.config.save()
        with self.assertRaises(ValidationError):
            generate_time_slots(self.institution)
