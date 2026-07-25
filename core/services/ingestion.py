"""
Tabilo — Course requirement ingestion service (Phase 2)

Single entry point for turning a "class division needs N periods/week of
this subject" row into a CourseRequirement, enforcing School vs. College
rules along the way. This is the seam Phase 5's CSV/Excel upload will call
into directly (one row -> one ingest_course_requirement() call) instead of
writing bulk-upload logic against the admin or the model layer directly.

School vs. College rules enforced here:
  - School rows can't carry an elective subject or an elective_group —
    electives are a College-only concept in Phase 1's model design.
  - A lab's block_size must evenly divide periods_per_week (e.g. a 6/wk lab
    can be two 3-hr blocks or three 2-hr blocks, but not an uneven split) —
    tighter than the DB's block_size <= periods_per_week constraint.
"""

from django.core.exceptions import ValidationError

from core.models import CourseRequirement, Institution


def ingest_course_requirement(
    *,
    institution,
    term,
    class_division,
    subject,
    periods_per_week,
    teacher=None,
    is_lab=False,
    block_size=1,
    elective_group=None,
):
    _validate_same_tenant(institution, term, class_division, subject, teacher, elective_group)
    _validate_institution_rules(institution, subject, elective_group, is_lab, block_size, periods_per_week)

    course_requirement, _ = CourseRequirement.objects.update_or_create(
        term=term,
        class_division=class_division,
        subject=subject,
        defaults={
            "institution": institution,
            "teacher": teacher,
            "periods_per_week": periods_per_week,
            "is_lab": is_lab,
            "block_size": block_size,
            "elective_group": elective_group,
        },
    )
    return course_requirement


def _validate_same_tenant(institution, term, class_division, subject, teacher, elective_group):
    for label, obj in [
        ("term", term),
        ("class_division", class_division),
        ("subject", subject),
        ("teacher", teacher),
        ("elective_group", elective_group),
    ]:
        if obj is not None and obj.institution_id != institution.id:
            raise ValidationError(f"{label} does not belong to {institution.name}.")


def _validate_institution_rules(institution, subject, elective_group, is_lab, block_size, periods_per_week):
    if institution.institution_type == Institution.SCHOOL and (subject.is_elective or elective_group is not None):
        raise ValidationError(
            "School institutions cannot carry an elective subject or an elective_group on a course requirement."
        )

    if is_lab:
        if block_size > periods_per_week:
            raise ValidationError(
                f"Lab block_size ({block_size}) cannot exceed periods_per_week ({periods_per_week})."
            )
        if periods_per_week % block_size != 0:
            raise ValidationError(
                f"Lab block_size ({block_size}) must evenly divide periods_per_week ({periods_per_week})."
            )
