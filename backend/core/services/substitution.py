"""
Tabilo — Smart Substitution (Proxy) Engine (Phase 8)

Suggests and records a same-day substitute teacher for one TimetableCell,
using real calendar dates via AcademicCalendarDay (Phase 4c) -- the first
consumer of that table. A substitution is a same-day overlay: it never
touches the underlying CourseRequirement/TimetableCell, so it stops
applying automatically once the date passes and never interferes with a
future re-solve.

Both suggest_substitutes() and record_substitution() share the exact same
exclusion rules (via _excluded_teacher_ids/_periods_today below) so a
suggestion can never be accepted by record_substitution() under looser
rules than it was generated with -- record_substitution() re-derives and
re-checks everything itself rather than trusting the caller's choice came
from suggest_substitutes() in the first place.
"""

from core.models import (
    AcademicCalendarDay,
    FacultyDutyBlock,
    Substitution,
    Teacher,
    TeacherSubjectEligibility,
    TimetableCell,
)


def suggest_substitutes(cell, date):
    day_identifier = _resolve_day_identifier(cell, date)
    excluded_teacher_ids = _excluded_teacher_ids(cell, date)
    eligible_teacher_ids = set(
        TeacherSubjectEligibility.objects.filter(
            institution=cell.institution, subject=cell.subject
        ).values_list("teacher_id", flat=True)
    )

    candidates = []
    for teacher in Teacher.objects.filter(institution=cell.institution, is_active=True).exclude(
        id__in=excluded_teacher_ids
    ):
        periods_today = _periods_today(teacher, cell, date, day_identifier)
        if periods_today + 1 > teacher.max_periods_per_day:
            continue
        is_subject_eligible = teacher.id in eligible_teacher_ids
        candidates.append({
            "teacher_id": teacher.id,
            "teacher_name": teacher.name,
            "is_subject_eligible": is_subject_eligible,
            "periods_today": periods_today,
            "reason": "Eligible for this subject" if is_subject_eligible else "Lowest current workload",
        })

    candidates.sort(key=lambda c: (0 if c["is_subject_eligible"] else 1, c["periods_today"], c["teacher_name"]))
    return candidates


def record_substitution(cell, date, substitute_teacher, reason=""):
    if substitute_teacher.institution_id != cell.institution_id:
        raise ValueError(f"{substitute_teacher.name} does not belong to {cell.institution.name}.")
    if not substitute_teacher.is_active:
        raise ValueError(f"{substitute_teacher.name} is not an active teacher.")

    day_identifier = _resolve_day_identifier(cell, date)

    # Re-validate from scratch -- never trust that a client-supplied
    # teacher id came from a suggest_substitutes() call, or that it's
    # still valid even if it did (another substitution could have been
    # recorded, or a duty block added, in between the two requests).
    excluded_teacher_ids = _excluded_teacher_ids(cell, date)
    if substitute_teacher.id in excluded_teacher_ids:
        raise ValueError(
            f"{substitute_teacher.name} is not available for this slot on {date} -- they're either "
            "the current teacher, on duty, already teaching another class at this time, or already "
            "assigned as a substitute elsewhere at this time on this date."
        )

    periods_today = _periods_today(substitute_teacher, cell, date, day_identifier)
    if periods_today + 1 > substitute_teacher.max_periods_per_day:
        raise ValueError(
            f"{substitute_teacher.name} would exceed their daily cap of "
            f"{substitute_teacher.max_periods_per_day} periods on {date}."
        )

    substitution, _ = Substitution.objects.update_or_create(
        original_cell=cell,
        date=date,
        defaults={
            "institution": cell.institution,
            "term": cell.term,
            "substitute_teacher": substitute_teacher,
            "reason": reason,
        },
    )
    return substitution


def _resolve_day_identifier(cell, date):
    try:
        calendar_day = AcademicCalendarDay.objects.get(institution=cell.institution, date=date)
    except AcademicCalendarDay.DoesNotExist:
        raise ValueError(f"{cell.institution.name} has no calendar entry for {date}.")
    if calendar_day.day_identifier is None:
        reason = calendar_day.label or ("Holiday" if calendar_day.is_holiday else "Not a working day")
        raise ValueError(f"{date} is not a working day for {cell.institution.name} ({reason}).")
    if calendar_day.day_identifier != cell.time_slot.day_identifier:
        raise ValueError(
            f"{date} is day {calendar_day.day_identifier} of the cycle, but this class is scheduled "
            f"on day {cell.time_slot.day_identifier} -- it doesn't occur on this date."
        )
    return calendar_day.day_identifier


def _excluded_teacher_ids(cell, date):
    """
    Every teacher who can't cover `cell` on `date`: the cell's own current
    teacher, anyone on a FacultyDutyBlock at this exact time_slot, anyone
    already teaching another class at this exact time_slot (their regular
    schedule), and anyone already assigned as a substitute elsewhere at
    this time_slot on this date -- excluding `cell`'s own existing
    Substitution (if any) so re-confirming the same substitute, or simply
    re-fetching suggestions for a cell that already has one, doesn't
    spuriously exclude them for "already being" themselves.
    """
    excluded = {cell.teacher_id}
    excluded.update(
        FacultyDutyBlock.objects.filter(term=cell.term, time_slot=cell.time_slot).values_list(
            "teacher_id", flat=True
        )
    )
    excluded.update(
        TimetableCell.objects.filter(term=cell.term, time_slot=cell.time_slot)
        .exclude(pk=cell.pk)
        .values_list("teacher_id", flat=True)
    )
    excluded.update(
        Substitution.objects.filter(date=date, original_cell__time_slot=cell.time_slot)
        .exclude(original_cell=cell)
        .values_list("substitute_teacher_id", flat=True)
    )
    return excluded


def _periods_today(teacher, cell, date, day_identifier):
    """
    How many periods `teacher` is already committed to on this real date:
    their regular schedule that day_identifier, plus any OTHER substitute
    assignments they've already picked up on this specific date --
    excluding `cell`'s own existing Substitution (if any), so
    re-validating an already-recorded assignment for this exact cell
    doesn't double-count it against itself.
    """
    regular = TimetableCell.objects.filter(
        term=cell.term, teacher=teacher, time_slot__day_identifier=day_identifier
    ).count()
    other_substitutions = (
        Substitution.objects.filter(date=date, substitute_teacher=teacher, original_cell__time_slot__day_identifier=day_identifier)
        .exclude(original_cell=cell)
        .count()
    )
    return regular + other_substitutions
