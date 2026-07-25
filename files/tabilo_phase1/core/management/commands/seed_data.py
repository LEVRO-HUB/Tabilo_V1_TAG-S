"""
Tabilo — Phase 1 seed data.

Populates two realistic tenants locally:
  1. A School Edition tenant (Greenwood Public School) — Mon-Sat weekly grid,
     fixed core subjects, no electives.
  2. A College Edition tenant (Anna University-affiliated engineering college)
     — Day 1-6 rotation, department structure, electives, and a locked
     contiguous lab block.

Idempotent: safe to re-run, uses get_or_create throughout.

Usage:
    python manage.py seed_data
"""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Institution,
    Department,
    AcademicTerm,
    Teacher,
    Subject,
    ClassDivision,
    TimeSlot,
    ElectiveGroup,
    CourseRequirement,
    FacultyDutyBlock,
)


class Command(BaseCommand):
    help = "Seed realistic local test data for a School scenario and a College scenario."

    @transaction.atomic
    def handle(self, *args, **options):
        self.seed_school()
        self.seed_college()
        self.stdout.write(self.style.SUCCESS("Seed data created successfully."))

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

        # Time grid: Mon(1)-Sat(6), 7 periods/day, one short break after P4.
        period_starts = [
            (1, datetime.time(9, 0), datetime.time(9, 45), False),
            (2, datetime.time(9, 45), datetime.time(10, 30), False),
            (3, datetime.time(10, 30), datetime.time(11, 15), False),
            (4, datetime.time(11, 15), datetime.time(12, 0), False),
            (5, datetime.time(12, 0), datetime.time(12, 30), True),  # lunch break
            (6, datetime.time(12, 30), datetime.time(13, 15), False),
            (7, datetime.time(13, 15), datetime.time(14, 0), False),
        ]
        for day in range(1, 7):  # Mon..Sat
            for period_number, start, end, is_break in period_starts:
                TimeSlot.objects.get_or_create(
                    institution=school,
                    day_identifier=day,
                    period_number=period_number,
                    defaults={"start_time": start, "end_time": end, "is_break": is_break},
                )

        # Course requirements: same 5 core subjects for every division, 6/wk each.
        for division in divisions.values():
            for subject_name, subject in subjects.items():
                CourseRequirement.objects.get_or_create(
                    institution=school,
                    term=term,
                    class_division=division,
                    subject=subject,
                    defaults={
                        "teacher": list(teachers.values())[hash(subject_name) % len(teachers)],
                        "periods_per_week": 6,
                        "is_lab": False,
                        "block_size": 1,
                    },
                )

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

        # Time grid: Day 1-6 rotation, 6 periods/day, mid-day break after P3.
        period_starts = [
            (1, datetime.time(9, 0), datetime.time(10, 0), False),
            (2, datetime.time(10, 0), datetime.time(11, 0), False),
            (3, datetime.time(11, 0), datetime.time(12, 0), False),
            (4, datetime.time(12, 0), datetime.time(13, 0), True),  # lunch break
            (5, datetime.time(13, 0), datetime.time(14, 0), False),
            (6, datetime.time(14, 0), datetime.time(15, 0), False),
        ]
        for day in range(1, 7):  # Day 1..Day 6
            for period_number, start, end, is_break in period_starts:
                TimeSlot.objects.get_or_create(
                    institution=college,
                    day_identifier=day,
                    period_number=period_number,
                    defaults={"start_time": start, "end_time": end, "is_break": is_break},
                )

        # Elective parallelism: both open electives share one group/slot pool.
        elective_group, _ = ElectiveGroup.objects.get_or_create(
            institution=college, term=term, name="Open Elective Pool - Sem 5"
        )

        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["CSE301"],
            defaults={"teacher": teachers["Dr. Lakshmi Venkat"], "periods_per_week": 4, "is_lab": False, "block_size": 1},
        )
        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["CSE302"],
            defaults={"teacher": teachers["Prof. Arjun Balaji"], "periods_per_week": 4, "is_lab": False, "block_size": 1},
        )
        # Contiguous lab locking: 6 hrs/week as two 3-hr blocks (e.g. P1-3 or P4-6).
        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["CSE301L"],
            defaults={"teacher": teachers["Dr. Meera Subramaniam"], "periods_per_week": 6, "is_lab": True, "block_size": 3},
        )
        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["ECE304"],
            defaults={"teacher": teachers["Prof. Vignesh Raghavan"], "periods_per_week": 3, "is_lab": False, "block_size": 1},
        )
        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["OE501A"],
            defaults={
                "teacher": teachers["Dr. Kavitha Shankar"], "periods_per_week": 2, "is_lab": False,
                "block_size": 1, "elective_group": elective_group,
            },
        )
        CourseRequirement.objects.get_or_create(
            institution=college, term=term, class_division=division, subject=subjects["OE501B"],
            defaults={
                "teacher": teachers["Prof. Vignesh Raghavan"], "periods_per_week": 2, "is_lab": False,
                "block_size": 1, "elective_group": elective_group,
            },
        )

        # Protected non-teaching windows (paper valuation, invigilation, etc.)
        exam_slot = TimeSlot.objects.get(institution=college, day_identifier=1, period_number=6)
        FacultyDutyBlock.objects.get_or_create(
            institution=college, term=term, teacher=teachers["Dr. Lakshmi Venkat"], time_slot=exam_slot,
            defaults={"duty_type": FacultyDutyBlock.NAAC_COMPLIANCE, "notes": "NAAC documentation window"},
        )
