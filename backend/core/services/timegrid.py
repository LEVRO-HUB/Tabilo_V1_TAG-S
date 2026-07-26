"""
Tabilo — Time grid generation service (Phase 2)

Turns an institution's TimeGridConfig into its TimeSlot rows for every day
in its cycle (day_identifier 1..institution.cycle_length), instead of
hardcoding period times per-institution in seed data.

Idempotent by default: if TimeSlot rows already exist for the institution,
generate_time_slots() returns them unchanged. Pass regenerate=True to
delete and rebuild from the current config — this refuses to run if any
TimetableCell still references the existing slots, since TimetableCell.time_slot
cascades on delete and a silent regenerate would wipe out real schedule data.
"""

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from core.models import TimeGridConfig, TimeSlot, TimetableCell


def generate_time_slots(institution, regenerate=False):
    try:
        config = institution.time_grid_config
    except TimeGridConfig.DoesNotExist:
        raise ValidationError(
            f"{institution.name} has no TimeGridConfig; create one before generating time slots."
        )
    config.clean()

    existing = TimeSlot.objects.filter(institution=institution)
    if not existing.exists():
        return _build_slots(institution, config)

    if not regenerate:
        return list(existing.order_by("day_identifier", "period_number"))

    if TimetableCell.objects.filter(institution=institution, time_slot__in=existing).exists():
        raise ValidationError(
            f"Cannot regenerate time slots for {institution.name}: existing TimetableCell rows "
            "reference the current slots. Clear or migrate the timetable before regenerating."
        )

    with transaction.atomic():
        existing.delete()
        return _build_slots(institution, config)


def _build_slots(institution, config):
    breaks_by_after_period = {entry["after_period"]: entry["duration_minutes"] for entry in config.breaks}
    period_duration = datetime.timedelta(minutes=config.period_duration_minutes)
    anchor_date = datetime.date.today()

    rows = []
    for day in range(1, institution.cycle_length + 1):
        cursor = datetime.datetime.combine(anchor_date, config.day_start_time)
        period_number = 0
        for teaching_period in range(1, config.periods_per_day + 1):
            period_number += 1
            start = cursor.time()
            cursor += period_duration
            rows.append(TimeSlot(
                institution=institution, day_identifier=day, period_number=period_number,
                start_time=start, end_time=cursor.time(), is_break=False,
            ))

            if teaching_period in breaks_by_after_period:
                period_number += 1
                break_start = cursor.time()
                cursor += datetime.timedelta(minutes=breaks_by_after_period[teaching_period])
                rows.append(TimeSlot(
                    institution=institution, day_identifier=day, period_number=period_number,
                    start_time=break_start, end_time=cursor.time(), is_break=True,
                ))

    with transaction.atomic():
        TimeSlot.objects.bulk_create(rows)
    return rows
