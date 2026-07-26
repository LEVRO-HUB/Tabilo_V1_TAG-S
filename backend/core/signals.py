"""
Tabilo — Phase 1 Signals

1. auto_create_general_department
   New School-type Institutions get a default "General" Department so
   schools never have to think about departments at all (colleges create
   their own real ones, e.g. "Computer Science").

2. enforce_single_active_term
   Guarantees at most one AcademicTerm is is_active=True per Institution,
   so "the current term" is always an unambiguous lookup.

3. enforce_teacher_workload_caps
   Before a TimetableCell is saved, checks the assigned teacher's existing
   load in that term against max_periods_per_day / max_periods_per_week
   and refuses to save if the new cell would breach either hard cap.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError

from core.models import Institution, Department, AcademicTerm, TimetableCell


@receiver(post_save, sender=Institution)
def auto_create_general_department(sender, instance, created, **kwargs):
    if created and instance.institution_type == Institution.SCHOOL:
        Department.objects.get_or_create(institution=instance, name="General")


@receiver(pre_save, sender=AcademicTerm)
def enforce_single_active_term(sender, instance, **kwargs):
    if instance.is_active:
        AcademicTerm.objects.filter(
            institution=instance.institution, is_active=True
        ).exclude(pk=instance.pk).update(is_active=False)


@receiver(pre_save, sender=TimetableCell)
def enforce_teacher_workload_caps(sender, instance, **kwargs):
    teacher = instance.teacher
    day_id = instance.time_slot.day_identifier

    existing_qs = TimetableCell.objects.filter(
        term=instance.term, teacher=teacher
    ).exclude(pk=instance.pk)

    periods_today = existing_qs.filter(time_slot__day_identifier=day_id).count()
    periods_this_week = existing_qs.count()

    if periods_today + 1 > teacher.max_periods_per_day:
        raise ValidationError(
            f"{teacher.name} would exceed their daily cap of "
            f"{teacher.max_periods_per_day} periods on day {day_id}."
        )
    if periods_this_week + 1 > teacher.max_periods_per_week:
        raise ValidationError(
            f"{teacher.name} would exceed their weekly cap of "
            f"{teacher.max_periods_per_week} periods."
        )
