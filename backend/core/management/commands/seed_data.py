"""
Tabilo — seed data.

Populates two realistic tenants locally:
  1. A School Edition tenant (Greenwood Public School) — Mon-Sat weekly grid,
     fixed core subjects, no electives.
  2. A College Edition tenant (Anna University-affiliated engineering college)
     — Day 1-6 rotation, department structure, electives, and a locked
     contiguous lab block.

Org structure (institutions, departments, teachers, subjects, divisions) is
seeded with plain get_or_create calls. Time grids and course requirements go
through the Phase 2 services (core/services/timegrid.py,
core/services/ingestion.py) instead of manual loops, so this command doubles
as an end-to-end proof that pipeline works, not just unit tests in isolation.

Idempotent: safe to re-run.

Usage:
    python manage.py seed_data
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Institution,
    UserProfile,
    Department,
    AcademicTerm,
    Teacher,
    Subject,
    ClassDivision,
    TimeGridConfig,
    TimeSlot,
    ElectiveGroup,
    FacultyDutyBlock,
)
from core.services.ingestion import ingest_course_requirement
from core.services.timegrid import generate_time_slots

# Local dev seed data ONLY -- a fixed, shared, publicly-known password like
# this must never be used for anything resembling production data.
DEV_PASSWORD = "tabilo-dev-2026"


class Command(BaseCommand):
    help = "Seed realistic local test data for a School scenario and a College scenario."

    @transaction.atomic
    def handle(self, *args, **options):
        self.seed_school()
        self.seed_college()
        self.stdout.write(self.style.SUCCESS("Seed data created successfully."))
        self.stdout.write(self.style.WARNING(
            "\nDev login credentials (local seed data ONLY -- never use fixed/shared "
            "credentials like these for anything resembling production data):\n"
            f"  greenwood_admin  / {DEV_PASSWORD}   (Greenwood Public School)\n"
            f"  coromandel_admin / {DEV_PASSWORD}   (Coromandel Institute of Engineering)\n"
        ))

    def seed_admin_user(self, institution, username):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"},
        )
        if created:
            user.set_password(DEV_PASSWORD)
            user.save()
        UserProfile.objects.get_or_create(
            user=user, defaults={"institution": institution, "role": UserProfile.ADMIN},
        )

    # ------------------------------------------------------------------
    # School scenario
    # ------------------------------------------------------------------

    def seed_school(self):
        school, _ = Institution.objects.get_or_create(
            name="Greenwood Public School",
            defaults={"institution_type": Institution.SCHOOL, "cycle_length": 6},
        )
        # Institution's post_save signal auto-creates the "General" department.
        general_dept = Department.objects.get(institution=school, name="General")

        term, _ = AcademicTerm.objects.get_or_create(
            institution=school,
            name="Annual 2026",
            defaults={
                "start_date": datetime.date(2026, 6, 1),
                "end_date": datetime.date(2027, 3, 31),
                "is_active": True,
            },
        )

        teachers = {}
        for name, email in [
            ("Anita Raman", "anita.raman@greenwood.edu"),
            ("Suresh Kumar", "suresh.kumar@greenwood.edu"),
            ("Deepa Nair", "deepa.nair@greenwood.edu"),
            ("Karthik Iyer", "karthik.iyer@greenwood.edu"),
            ("Priya Menon", "priya.menon@greenwood.edu"),
        ]:
            teacher, _ = Teacher.objects.get_or_create(
                institution=school,
                email=email,
                defaults={"name": name, "max_periods_per_day": 6, "max_periods_per_week": 30},
            )
            teachers[name] = teacher

        subjects = {}
        for name, code in [
            ("Mathematics", "SCH-MATH8"),
            ("Science", "SCH-SCI8"),
            ("English", "SCH-ENG8"),
            ("Social Science", "SCH-SOC8"),
            ("Second Language", "SCH-LANG8"),
        ]:
            subject, _ = Subject.objects.get_or_create(
                institution=school,
                code=code,
                defaults={"name": name, "department": general_dept, "is_elective": False},
            )
            subjects[name] = subject

        divisions = {}
        for section in ["A", "B"]:
            division, _ = ClassDivision.objects.get_or_create(
                institution=school,
                department=general_dept,
                name="Grade 8",
                section=section,
            )
            divisions[section] = division

        # Time grid: Mon(1)-Sat(6), 6 teaching periods/day, one 30-min break
        # after period 4 (same 9:00-14:00 grid as Phase 1's hardcoded slots).
        TimeGridConfig.objects.get_or_create(
            institution=school,
            defaults={
                "periods_per_day": 6,
                "period_duration_minutes": 45,
                "day_start_time": datetime.time(9, 0),
                "breaks": [{"after_period": 4, "duration_minutes": 30}],
            },
        )
        generate_time_slots(school)

        # Course requirements: same 5 core subjects for every division, 6/wk each.
        # Teacher assignment is index-based (not hash(subject_name)-based) so
        # re-running seed_data is actually deterministic — Python's str hash
        # is salted per-process by default and would otherwise reshuffle
        # teachers on every rerun.
        teacher_list = list(teachers.values())
        for division in divisions.values():
            for idx, subject in enumerate(subjects.values()):
                ingest_course_requirement(
                    institution=school,
                    term=term,
                    class_division=division,
                    subject=subject,
                    periods_per_week=6,
                    teacher=teacher_list[idx % len(teacher_list)],
                    is_lab=False,
                    block_size=1,
                )

        self.seed_admin_user(school, "greenwood_admin")

    # ------------------------------------------------------------------
    # College scenario (Anna University-affiliated engineering college)
    # ------------------------------------------------------------------

    def seed_college(self):
        college, _ = Institution.objects.get_or_create(
            name="Coromandel Institute of Engineering",
            defaults={"institution_type": Institution.COLLEGE, "cycle_length": 6},
        )

        dept_cse, _ = Department.objects.get_or_create(institution=college, name="Computer Science")
        dept_ece, _ = Department.objects.get_or_create(institution=college, name="Electronics & Communication")

        term, _ = AcademicTerm.objects.get_or_create(
            institution=college,
            name="Odd Semester 2026-27",
            defaults={
                "start_date": datetime.date(2026, 7, 1),
                "end_date": datetime.date(2026, 11, 30),
                "is_active": True,
            },
        )

        teachers = {}
        for name, email, dept in [
            ("Dr. Lakshmi Venkat", "lakshmi.venkat@coromandel.edu", dept_cse),
            ("Prof. Arjun Balaji", "arjun.balaji@coromandel.edu", dept_cse),
            ("Dr. Meera Subramaniam", "meera.subramaniam@coromandel.edu", dept_cse),
            ("Prof. Vignesh Raghavan", "vignesh.raghavan@coromandel.edu", dept_ece),
            ("Dr. Kavitha Shankar", "kavitha.shankar@coromandel.edu", dept_ece),
        ]:
            # Anna University Asst. Professor cap: 24 hrs/week.
            teacher, _ = Teacher.objects.get_or_create(
                institution=college,
                email=email,
                defaults={"name": name, "max_periods_per_day": 5, "max_periods_per_week": 24},
            )
            teachers[name] = teacher

        subjects = {}
        subject_specs = [
            ("Data Structures", "CSE301", dept_cse, False),
            ("Operating Systems", "CSE302", dept_cse, False),
            ("Data Structures Lab", "CSE301L", dept_cse, False),  # 6-hr lab, block_size=3
            ("Open Elective - AI Basics", "OE501A", dept_cse, True),
            ("Open Elective - Robotics", "OE501B", dept_ece, True),
            ("Digital Signal Processing", "ECE304", dept_ece, False),
        ]
        for name, code, dept, is_elective in subject_specs:
            subject, _ = Subject.objects.get_or_create(
                institution=college,
                code=code,
                defaults={"name": name, "department": dept, "is_elective": is_elective},
            )
            subjects[code] = subject

        division, _ = ClassDivision.objects.get_or_create(
            institution=college,
            department=dept_cse,
            name="B.Tech CSE III Year",
            section="A",
        )

        # Time grid: Day 1-6 rotation, 5 teaching periods/day, 1-hr lunch
        # break after period 3 (same 9:00-15:00 grid as Phase 1's hardcoded
        # slots — the break has the same 60-min duration as a period here).
        TimeGridConfig.objects.get_or_create(
            institution=college,
            defaults={
                "periods_per_day": 5,
                "period_duration_minutes": 60,
                "day_start_time": datetime.time(9, 0),
                "breaks": [{"after_period": 3, "duration_minutes": 60}],
            },
        )
        generate_time_slots(college)

        # Elective parallelism: both open electives share one group/slot pool.
        elective_group, _ = ElectiveGroup.objects.get_or_create(
            institution=college, term=term, name="Open Elective Pool - Sem 5"
        )

        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["CSE301"],
            teacher=teachers["Dr. Lakshmi Venkat"], periods_per_week=4, is_lab=False, block_size=1,
        )
        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["CSE302"],
            teacher=teachers["Prof. Arjun Balaji"], periods_per_week=4, is_lab=False, block_size=1,
        )
        # Contiguous lab locking: 6 hrs/week as two 3-hr blocks (e.g. P1-3 or P4-6).
        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["CSE301L"],
            teacher=teachers["Dr. Meera Subramaniam"], periods_per_week=6, is_lab=True, block_size=3,
        )
        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["ECE304"],
            teacher=teachers["Prof. Vignesh Raghavan"], periods_per_week=3, is_lab=False, block_size=1,
        )
        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["OE501A"],
            teacher=teachers["Dr. Kavitha Shankar"], periods_per_week=2, is_lab=False,
            block_size=1, elective_group=elective_group,
        )
        ingest_course_requirement(
            institution=college, term=term, class_division=division, subject=subjects["OE501B"],
            teacher=teachers["Prof. Vignesh Raghavan"], periods_per_week=2, is_lab=False,
            block_size=1, elective_group=elective_group,
        )

        # Protected non-teaching windows (paper valuation, invigilation, etc.)
        exam_slot = TimeSlot.objects.get(institution=college, day_identifier=1, period_number=6)
        FacultyDutyBlock.objects.get_or_create(
            institution=college, term=term, teacher=teachers["Dr. Lakshmi Venkat"], time_slot=exam_slot,
            defaults={"duty_type": FacultyDutyBlock.NAAC_COMPLIANCE, "notes": "NAAC documentation window"},
        )

        self.seed_admin_user(college, "coromandel_admin")
