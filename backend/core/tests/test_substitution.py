import datetime

from django.test import TestCase

from core.models import (
    AcademicCalendarDay,
    AcademicTerm,
    ClassDivision,
    Department,
    FacultyDutyBlock,
    Institution,
    Subject,
    Substitution,
    Teacher,
    TeacherSubjectEligibility,
    TimeGridConfig,
    TimetableCell,
)
from core.services.substitution import record_substitution, suggest_substitutes
from core.services.timegrid import generate_time_slots


class SubstitutionTestCase(TestCase):
    """Same fixture-building style as core/tests/test_solver.py, but cells
    are built directly (not via the solver) for precise control over
    exactly which teacher occupies which slot -- what the exclusion rules
    under test actually key off."""

    DATE = datetime.date(2026, 8, 3)  # arbitrary real date, mapped to day_identifier=1 below

    def make_institution(self, cycle_length=3):
        return Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=cycle_length
        )

    def make_grid(self, institution, periods_per_day=3):
        TimeGridConfig.objects.create(
            institution=institution, periods_per_day=periods_per_day, period_duration_minutes=60,
            day_start_time=datetime.time(9, 0), breaks=[],
        )
        return generate_time_slots(institution)

    def make_calendar_day(self, institution, date, day_identifier=1):
        return AcademicCalendarDay.objects.create(
            institution=institution, date=date, day_identifier=day_identifier,
        )

    def make_term(self, institution, name="Term"):
        return AcademicTerm.objects.create(
            institution=institution, name=name,
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 3, 31),
        )

    def make_teacher(self, institution, email, max_periods_per_day=10, max_periods_per_week=40, is_active=True):
        return Teacher.objects.create(
            institution=institution, name=email, email=email, is_active=is_active,
            max_periods_per_day=max_periods_per_day, max_periods_per_week=max_periods_per_week,
        )

    def make_cell(self, institution, term, class_division, time_slot, subject, teacher):
        return TimetableCell.objects.create(
            institution=institution, term=term, class_division=class_division, time_slot=time_slot,
            subject=subject, teacher=teacher,
        )

    def setUp(self):
        self.institution = self.make_institution()
        self.slots = self.make_grid(self.institution)  # day 1..3, period 1..3 each (9 slots)
        self.calendar_day = self.make_calendar_day(self.institution, self.DATE, day_identifier=1)
        self.term = self.make_term(self.institution)
        self.department = Department.objects.create(institution=self.institution, name="Dept")
        self.division_a = ClassDivision.objects.create(
            institution=self.institution, department=self.department, name="Div A", section="A"
        )
        self.division_b = ClassDivision.objects.create(
            institution=self.institution, department=self.department, name="Div B", section="B"
        )
        self.subject = Subject.objects.create(institution=self.institution, department=self.department, name="Math", code="MATH1")
        self.original_teacher = self.make_teacher(self.institution, "original@test.edu")

        # The cell under test: Div A, day 1 / period 1, absent original_teacher.
        self.slot_day1_period1 = next(s for s in self.slots if s.day_identifier == 1 and s.period_number == 1)
        self.slot_day1_period2 = next(s for s in self.slots if s.day_identifier == 1 and s.period_number == 2)
        self.cell = self.make_cell(
            self.institution, self.term, self.division_a, self.slot_day1_period1, self.subject, self.original_teacher
        )


class SuggestionRankingTests(SubstitutionTestCase):
    def test_subject_eligible_ranked_above_non_eligible(self):
        eligible = self.make_teacher(self.institution, "eligible@test.edu")
        TeacherSubjectEligibility.objects.create(institution=self.institution, teacher=eligible, subject=self.subject)
        non_eligible = self.make_teacher(self.institution, "non_eligible@test.edu")

        candidates = suggest_substitutes(self.cell, self.DATE)

        ids_in_order = [c["teacher_id"] for c in candidates]
        self.assertLess(ids_in_order.index(eligible.id), ids_in_order.index(non_eligible.id))
        eligible_candidate = next(c for c in candidates if c["teacher_id"] == eligible.id)
        self.assertEqual(eligible_candidate["reason"], "Eligible for this subject")

    def test_lower_workload_breaks_ties_among_non_eligible(self):
        light = self.make_teacher(self.institution, "light@test.edu")
        busy = self.make_teacher(self.institution, "busy@test.edu")
        # busy already teaches one other period that same day (day 1).
        self.make_cell(self.institution, self.term, self.division_b, self.slot_day1_period2, self.subject, busy)

        candidates = suggest_substitutes(self.cell, self.DATE)

        ids_in_order = [c["teacher_id"] for c in candidates]
        self.assertLess(ids_in_order.index(light.id), ids_in_order.index(busy.id))
        busy_candidate = next(c for c in candidates if c["teacher_id"] == busy.id)
        self.assertEqual(busy_candidate["periods_today"], 1)
        light_candidate = next(c for c in candidates if c["teacher_id"] == light.id)
        self.assertEqual(light_candidate["periods_today"], 0)
        self.assertEqual(light_candidate["reason"], "Lowest current workload")


class SuggestionExclusionTests(SubstitutionTestCase):
    def test_excludes_cells_own_current_teacher(self):
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(self.original_teacher.id, [c["teacher_id"] for c in candidates])

    def test_excludes_teacher_on_duty_block_at_that_slot(self):
        on_duty = self.make_teacher(self.institution, "onduty@test.edu")
        FacultyDutyBlock.objects.create(
            institution=self.institution, term=self.term, teacher=on_duty, time_slot=self.slot_day1_period1,
            duty_type=FacultyDutyBlock.INVIGILATION,
        )
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(on_duty.id, [c["teacher_id"] for c in candidates])

    def test_excludes_teacher_already_teaching_another_class_at_that_exact_slot(self):
        busy_elsewhere = self.make_teacher(self.institution, "busy_elsewhere@test.edu")
        self.make_cell(
            self.institution, self.term, self.division_b, self.slot_day1_period1, self.subject, busy_elsewhere
        )
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(busy_elsewhere.id, [c["teacher_id"] for c in candidates])

    def test_excludes_teacher_already_substituting_elsewhere_at_that_slot_same_date(self):
        other_cell = self.make_cell(
            self.institution, self.term, self.division_b, self.slot_day1_period1, self.subject, self.make_teacher(
                self.institution, "other_original@test.edu"
            )
        )
        double_booked = self.make_teacher(self.institution, "double_booked@test.edu")
        Substitution.objects.create(
            institution=self.institution, term=self.term, original_cell=other_cell, date=self.DATE,
            substitute_teacher=double_booked,
        )
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(double_booked.id, [c["teacher_id"] for c in candidates])

    def test_excludes_teacher_who_would_exceed_daily_cap(self):
        capped = self.make_teacher(self.institution, "capped@test.edu", max_periods_per_day=1)
        self.make_cell(self.institution, self.term, self.division_b, self.slot_day1_period2, self.subject, capped)
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(capped.id, [c["teacher_id"] for c in candidates])

    def test_excludes_inactive_teacher(self):
        inactive = self.make_teacher(self.institution, "inactive@test.edu", is_active=False)
        candidates = suggest_substitutes(self.cell, self.DATE)
        self.assertNotIn(inactive.id, [c["teacher_id"] for c in candidates])

    def test_non_working_day_raises(self):
        off_date = self.DATE + datetime.timedelta(days=100)  # no AcademicCalendarDay entry
        with self.assertRaises(ValueError):
            suggest_substitutes(self.cell, off_date)

    def test_holiday_raises(self):
        holiday = self.DATE + datetime.timedelta(days=1)
        AcademicCalendarDay.objects.create(
            institution=self.institution, date=holiday, day_identifier=None, is_holiday=True, label="Founders Day"
        )
        with self.assertRaises(ValueError):
            suggest_substitutes(self.cell, holiday)

    def test_date_mapping_to_a_different_day_identifier_raises(self):
        other_day_date = self.DATE + datetime.timedelta(days=2)
        AcademicCalendarDay.objects.create(institution=self.institution, date=other_day_date, day_identifier=2)
        # cell is on day_identifier=1, but other_day_date maps to day 2 -- doesn't occur on this date.
        with self.assertRaises(ValueError):
            suggest_substitutes(self.cell, other_day_date)


class RecordSubstitutionTests(SubstitutionTestCase):
    def test_records_a_valid_substitution(self):
        replacement = self.make_teacher(self.institution, "replacement@test.edu")
        substitution = record_substitution(self.cell, self.DATE, replacement, reason="Sick leave")

        self.assertEqual(Substitution.objects.count(), 1)
        self.assertEqual(substitution.original_cell, self.cell)
        self.assertEqual(substitution.substitute_teacher, replacement)
        self.assertEqual(substitution.date, self.DATE)
        self.assertEqual(substitution.reason, "Sick leave")

    def test_upserts_on_original_cell_and_date(self):
        first_choice = self.make_teacher(self.institution, "first@test.edu")
        second_choice = self.make_teacher(self.institution, "second@test.edu")
        record_substitution(self.cell, self.DATE, first_choice)
        record_substitution(self.cell, self.DATE, second_choice)

        self.assertEqual(Substitution.objects.count(), 1)
        self.assertEqual(Substitution.objects.get().substitute_teacher, second_choice)

    def test_reconfirming_the_same_substitute_does_not_self_exclude(self):
        replacement = self.make_teacher(self.institution, "replacement@test.edu")
        record_substitution(self.cell, self.DATE, replacement, reason="Initial")
        # Re-recording the SAME substitute for the SAME cell+date must not
        # be rejected by the "already substituting elsewhere at this slot"
        # rule matching their own prior assignment for this exact cell.
        substitution = record_substitution(self.cell, self.DATE, replacement, reason="Updated reason")
        self.assertEqual(Substitution.objects.count(), 1)
        self.assertEqual(substitution.reason, "Updated reason")

    def test_rejects_a_candidate_that_became_invalid_since_being_suggested(self):
        """Proves record_substitution() re-validates server-side rather
        than trusting the caller's choice -- simulates the race where a
        candidate was valid when suggested, but a duty block was added
        for them before the admin's choice was submitted."""
        candidate = self.make_teacher(self.institution, "candidate@test.edu")

        candidates_before = suggest_substitutes(self.cell, self.DATE)
        self.assertIn(candidate.id, [c["teacher_id"] for c in candidates_before])

        # The world changes between suggestion and confirmation.
        FacultyDutyBlock.objects.create(
            institution=self.institution, term=self.term, teacher=candidate, time_slot=self.slot_day1_period1,
            duty_type=FacultyDutyBlock.INVIGILATION,
        )

        with self.assertRaises(ValueError):
            record_substitution(self.cell, self.DATE, candidate)
        self.assertEqual(Substitution.objects.count(), 0)

    def test_rejects_cross_institution_substitute(self):
        other_institution = self.make_institution()
        foreign_teacher = self.make_teacher(other_institution, "foreign@test.edu")
        with self.assertRaises(ValueError):
            record_substitution(self.cell, self.DATE, foreign_teacher)
        self.assertEqual(Substitution.objects.count(), 0)

    def test_rejects_inactive_substitute(self):
        inactive = self.make_teacher(self.institution, "inactive@test.edu", is_active=False)
        with self.assertRaises(ValueError):
            record_substitution(self.cell, self.DATE, inactive)
        self.assertEqual(Substitution.objects.count(), 0)

    def test_rejects_teacher_exceeding_daily_cap(self):
        capped = self.make_teacher(self.institution, "capped@test.edu", max_periods_per_day=1)
        self.make_cell(self.institution, self.term, self.division_b, self.slot_day1_period2, self.subject, capped)
        with self.assertRaises(ValueError):
            record_substitution(self.cell, self.DATE, capped)
        self.assertEqual(Substitution.objects.count(), 0)
