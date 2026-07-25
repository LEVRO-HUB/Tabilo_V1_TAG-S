"""
Tabilo — write a solve_feasibility() SolverResult's assignments to TimetableCell rows.

Note: this only ever creates or updates cells that appear in `assignments`;
it does not delete stale unlocked cells left over from a previous solver run
that the new solution no longer uses (e.g. if a rerun happens to place a
CourseRequirement on different days). Full regenerate/cleanup semantics are
out of scope for 3a's feasibility-only pass.
"""

from django.db import transaction

from core.models import ClassDivision, CourseRequirement, Subject, Teacher, TimeSlot, TimetableCell


def apply_solution(term, assignments):
    course_requirements = CourseRequirement.objects.in_bulk({a["course_requirement_id"] for a in assignments})
    class_divisions = ClassDivision.objects.in_bulk({a["class_division_id"] for a in assignments})
    subjects = Subject.objects.in_bulk({a["subject_id"] for a in assignments})
    time_slots = TimeSlot.objects.in_bulk({a["time_slot_id"] for a in assignments})
    teachers = Teacher.objects.in_bulk({a["teacher_id"] for a in assignments})

    # Belt-and-suspenders: solve_feasibility() already excludes locked cells'
    # (class_division, time_slot) from every active CR's domain, so this
    # should never actually match — but "do not touch locked cells" is a
    # hard invariant, not an assumption, so it's enforced here too.
    locked_keys = set(
        TimetableCell.objects.filter(term=term, is_locked=True).values_list(
            "class_division_id", "time_slot_id", "subject_id"
        )
    )

    written = 0
    with transaction.atomic():
        for assignment in assignments:
            key = (assignment["class_division_id"], assignment["time_slot_id"], assignment["subject_id"])
            if key in locked_keys:
                continue
            course_requirement = course_requirements[assignment["course_requirement_id"]]
            TimetableCell.objects.update_or_create(
                term=term,
                class_division=class_divisions[assignment["class_division_id"]],
                time_slot=time_slots[assignment["time_slot_id"]],
                subject=subjects[assignment["subject_id"]],
                defaults={
                    "institution": term.institution,
                    "teacher": teachers[assignment["teacher_id"]],
                    "course_requirement": course_requirement,
                    "elective_group": course_requirement.elective_group,
                    "is_locked": False,
                },
            )
            written += 1
    return written
