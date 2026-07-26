"""
Tabilo — Academic calendar generation service (Phase 4c)

Maps real calendar dates to the abstract day_identifier cycle that
TimeSlot/TimetableCell/the solver already operate on -- the piece Phase 4b's
substitution engine needs, since a real teacher absence happens on a real
date ("Aug 15"), not an abstract "Day 3".

Idempotent via update_or_create per (institution, date): unlike
generate_time_slots(), there's no destructive guard here, because nothing
else in the schema references AcademicCalendarDay by foreign key -- it's
looked up by date at call time, so there's nothing to orphan by
overwriting it. Safe to call again to extend a range or fix a holiday list.

Note: each call computes day_identifier fresh starting from its own
start_date -- for COLLEGE's rotating counter, calling generate_calendar()
again for a DIFFERENT (non-identical) but overlapping range does NOT resume
the rotation from where a prior call left off. Calling with the exact same
range is fully idempotent; calling with a shifted range recomputes the
rotation from that range's own start_date.

School vs College day_identifier assignment (per the original PRD split):
  - SCHOOL: a fixed mapping from Python weekday -> cycle position, built
    once from the in-order weekdays that aren't weekly off. A holiday only
    blanks out that one date -- it never shifts other weekdays' mapping.
    The number of working weekdays this produces MUST equal
    institution.cycle_length -- generate_calendar() raises ValueError if it
    doesn't, rather than silently assigning a day_identifier (e.g. 6) that
    has no corresponding TimeSlot rows for a 5-day-week institution.
  - COLLEGE: a rotating counter that only advances on genuine working days,
    wrapping modulo cycle_length. A holiday just pauses the rotation; the
    next working day picks up the Day-Order position the holiday would
    have had. This is self-consistent with cycle_length by construction
    (the modulo uses it directly), so no separate validation is needed here.
"""

import datetime

from core.models import AcademicCalendarDay, Institution


def generate_calendar(institution, start_date, end_date, weekly_off_weekdays=None, holiday_dates=None):
    weekly_off_weekdays = {6} if weekly_off_weekdays is None else set(weekly_off_weekdays)
    holiday_dates = holiday_dates or {}

    weekday_to_day_identifier = None
    if institution.institution_type == Institution.SCHOOL:
        working_weekdays = [weekday for weekday in range(7) if weekday not in weekly_off_weekdays]
        if len(working_weekdays) != institution.cycle_length:
            raise ValueError(
                f"{institution.name} has cycle_length={institution.cycle_length}, but "
                f"weekly_off_weekdays={sorted(weekly_off_weekdays)} leaves {len(working_weekdays)} "
                "working weekdays -- these must match. Pass a weekly_off_weekdays set whose size "
                "is (7 - cycle_length), e.g. a 5-day week needs 2 weekdays off, not 1."
            )
        weekday_to_day_identifier = {weekday: position + 1 for position, weekday in enumerate(working_weekdays)}

    rows = []
    working_day_count = 0
    current = start_date
    while current <= end_date:
        is_off, is_holiday, label = _classify_date(current, weekly_off_weekdays, holiday_dates)

        if is_off:
            day_identifier = None
        elif weekday_to_day_identifier is not None:
            day_identifier = weekday_to_day_identifier[current.weekday()]
        else:
            day_identifier = (working_day_count % institution.cycle_length) + 1
            working_day_count += 1

        row, _ = AcademicCalendarDay.objects.update_or_create(
            institution=institution,
            date=current,
            defaults={"day_identifier": day_identifier, "is_holiday": is_holiday, "label": label},
        )
        rows.append(row)
        current += datetime.timedelta(days=1)

    return rows


def _classify_date(date, weekly_off_weekdays, holiday_dates):
    """
    Precedence when a date is both an explicit holiday AND a routine weekly
    off day: the explicit holiday wins for is_holiday/label (it's the more
    specific, deliberately-provided information) — the date is a non-working
    day either way, this only affects which is_holiday/label it's recorded
    with.
    """
    if date in holiday_dates:
        label = holiday_dates[date] or "Holiday"
        return True, True, label
    if date.weekday() in weekly_off_weekdays:
        return True, False, "Weekly off"
    return False, False, ""
