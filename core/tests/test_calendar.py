import datetime

from django.test import TestCase

from core.models import AcademicCalendarDay, Institution
from core.services.calendar import generate_calendar


class SchoolCalendarTests(TestCase):
    def test_fixed_weekday_mapping_and_holiday_does_not_shift_other_days(self):
        institution = Institution.objects.create(
            name="Test School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=20)  # 3 weeks, plenty of buffer

        # A Wednesday in the first week, used as a mid-week holiday.
        first_wednesday = start + datetime.timedelta(days=(2 - start.weekday()) % 7)
        holiday_dates = {first_wednesday: "Mid-week Holiday"}

        rows = generate_calendar(institution, start, end, weekly_off_weekdays={6}, holiday_dates=holiday_dates)
        by_date = {row.date: row for row in rows}

        # Every Monday in range shares the same fixed day_identifier.
        mondays = [d for d in by_date if d.weekday() == 0]
        self.assertGreaterEqual(len(mondays), 2)
        monday_identifiers = {by_date[d].day_identifier for d in mondays}
        self.assertEqual(len(monday_identifiers), 1)
        self.assertIsNotNone(next(iter(monday_identifiers)))

        # The holiday itself has no day_identifier.
        self.assertIsNone(by_date[first_wednesday].day_identifier)
        self.assertTrue(by_date[first_wednesday].is_holiday)
        self.assertEqual(by_date[first_wednesday].label, "Mid-week Holiday")

        # Thursday/Friday/Saturday of that SAME week keep their normal
        # fixed-weekday day_identifier -- the holiday doesn't shift them.
        # Compare against the same weekday the following week (not a holiday).
        for offset in (1, 2, 3):  # Thu, Fri, Sat
            this_week = first_wednesday + datetime.timedelta(days=offset)
            next_week = this_week + datetime.timedelta(days=7)
            self.assertIsNotNone(by_date[this_week].day_identifier)
            self.assertEqual(by_date[this_week].day_identifier, by_date[next_week].day_identifier)


class SchoolCycleLengthValidationTests(TestCase):
    def test_mismatched_weekly_off_and_cycle_length_raises(self):
        # cycle_length=5 (a 5-day week) but only Sunday is off -> 6 working
        # weekdays, not 5. Without validation this would silently assign
        # Saturday day_identifier=6, a value with no TimeSlot rows at all
        # for this institution (generate_time_slots only goes up to
        # cycle_length). Must raise instead of writing bad data.
        institution = Institution.objects.create(
            name="Mismatched School", institution_type=Institution.SCHOOL, cycle_length=5
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=6)

        with self.assertRaises(ValueError):
            generate_calendar(institution, start, end, weekly_off_weekdays={6})

        self.assertEqual(AcademicCalendarDay.objects.filter(institution=institution).count(), 0)

    def test_matching_weekly_off_and_cycle_length_succeeds(self):
        # cycle_length=5 with both Saturday and Sunday off -> exactly 5
        # working weekdays, matches.
        institution = Institution.objects.create(
            name="Matched School", institution_type=Institution.SCHOOL, cycle_length=5
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=6)

        rows = generate_calendar(institution, start, end, weekly_off_weekdays={5, 6})

        for row in rows:
            if row.date.weekday() in (5, 6):
                self.assertIsNone(row.day_identifier)
            else:
                self.assertIsNotNone(row.day_identifier)
                self.assertLessEqual(row.day_identifier, 5)


class CollegeCalendarTests(TestCase):
    def test_rotation_pauses_on_holiday_and_wraps_around_cycle_length(self):
        institution = Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=3
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=12)  # ~11 working days minus 1 holiday -> wraps 3+ times

        first_thursday = start + datetime.timedelta(days=(3 - start.weekday()) % 7)
        holiday_dates = {first_thursday: "College Holiday"}

        rows = generate_calendar(institution, start, end, weekly_off_weekdays={6}, holiday_dates=holiday_dates)
        by_date = {row.date: row for row in rows}

        self.assertIsNone(by_date[first_thursday].day_identifier)
        self.assertTrue(by_date[first_thursday].is_holiday)

        # The rotation is a pure sequential count (1..cycle_length, wrapping)
        # over ONLY the actual working days, in date order -- this directly
        # proves the holiday paused the rotation rather than resetting or
        # skipping a position for the days that follow it.
        working_days_in_order = sorted(d for d, row in by_date.items() if row.day_identifier is not None)
        expected = [(i % institution.cycle_length) + 1 for i in range(len(working_days_in_order))]
        actual = [by_date[d].day_identifier for d in working_days_in_order]
        self.assertEqual(actual, expected)

        # Confirms it actually wraps past cycle_length back to 1 more than once.
        self.assertGreaterEqual(actual.count(1), 2)


class CalendarDayClassificationTests(TestCase):
    def test_weekly_off_dates_have_no_day_identifier(self):
        institution = Institution.objects.create(
            name="Test School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=13)
        rows = generate_calendar(institution, start, end, weekly_off_weekdays={6})

        for row in rows:
            if row.date.weekday() == 6:
                self.assertIsNone(row.day_identifier)
                self.assertFalse(row.is_holiday)
                self.assertEqual(row.label, "Weekly off")
            else:
                self.assertIsNotNone(row.day_identifier)

    def test_holiday_dates_have_no_day_identifier_and_carry_label(self):
        institution = Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=6
        )
        start = datetime.date(2026, 8, 1)
        end = start + datetime.timedelta(days=13)
        holiday = start + datetime.timedelta(days=3)
        while holiday.weekday() == 6:  # keep it off the weekly-off day for a clean single-cause check
            holiday += datetime.timedelta(days=1)

        rows = generate_calendar(
            institution, start, end, weekly_off_weekdays={6}, holiday_dates={holiday: "Independence Day"}
        )
        row = next(r for r in rows if r.date == holiday)

        self.assertIsNone(row.day_identifier)
        self.assertTrue(row.is_holiday)
        self.assertEqual(row.label, "Independence Day")


class CalendarIdempotencyTests(TestCase):
    def test_calling_twice_for_same_range_is_idempotent(self):
        institution = Institution.objects.create(
            name="Test College", institution_type=Institution.COLLEGE, cycle_length=4
        )
        start = datetime.date(2026, 9, 1)
        end = start + datetime.timedelta(days=9)
        holiday_dates = {start + datetime.timedelta(days=4): "Some Holiday"}

        first_rows = generate_calendar(institution, start, end, weekly_off_weekdays={6}, holiday_dates=holiday_dates)
        second_rows = generate_calendar(institution, start, end, weekly_off_weekdays={6}, holiday_dates=holiday_dates)

        expected_count = (end - start).days + 1
        self.assertEqual(AcademicCalendarDay.objects.filter(institution=institution).count(), expected_count)

        first_by_date = {r.date: (r.day_identifier, r.is_holiday, r.label) for r in first_rows}
        second_by_date = {r.date: (r.day_identifier, r.is_holiday, r.label) for r in second_rows}
        self.assertEqual(first_by_date, second_by_date)


class HolidayOnWeeklyOffPrecedenceTests(TestCase):
    def test_holiday_on_a_weekly_off_date_does_not_crash_and_holiday_wins(self):
        institution = Institution.objects.create(
            name="Test School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        start = datetime.date(2026, 7, 1)
        end = start + datetime.timedelta(days=13)
        sunday = start + datetime.timedelta(days=(6 - start.weekday()) % 7)

        rows = generate_calendar(
            institution, start, end, weekly_off_weekdays={6}, holiday_dates={sunday: "Special Sunday"}
        )
        row = next(r for r in rows if r.date == sunday)

        self.assertIsNone(row.day_identifier)
        self.assertTrue(row.is_holiday)
        self.assertEqual(row.label, "Special Sunday")
