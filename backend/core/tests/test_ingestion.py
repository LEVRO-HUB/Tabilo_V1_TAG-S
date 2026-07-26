import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    ElectiveGroup,
    Institution,
    Subject,
    Teacher,
)
from core.services.ingestion import ingest_course_requirement


class IngestCourseRequirementSchoolTests(TestCase):
    """School-mode rules: no electives, no elective_group."""

    def setUp(self):
        self.school = Institution.objects.create(
            name="Greenwood Public School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        self.department = Department.objects.get(institution=self.school, name="General")
        self.term = AcademicTerm.objects.create(
            institution=self.school, name="Annual 2026",
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 3, 31),
        )
        self.division = ClassDivision.objects.create(
            institution=self.school, department=self.department, name="Grade 8", section="A"
        )
        self.teacher = Teacher.objects.create(
            institution=self.school, name="Anita Raman", email="anita@greenwood.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )

    def test_ordinary_requirement_succeeds(self):
        subject = Subject.objects.create(
            institution=self.school, department=self.department, name="Mathematics", code="MATH8"
        )
        req = ingest_course_requirement(
            institution=self.school, term=self.term, class_division=self.division, subject=subject,
            periods_per_week=6, teacher=self.teacher,
        )
        self.assertEqual(CourseRequirement.objects.count(), 1)
        self.assertEqual(req.periods_per_week, 6)

    def test_elective_subject_rejected(self):
        elective_subject = Subject.objects.create(
            institution=self.school, department=self.department, name="Art Elective", code="ART8",
            is_elective=True,
        )
        with self.assertRaises(ValidationError):
            ingest_course_requirement(
                institution=self.school, term=self.term, class_division=self.division,
                subject=elective_subject, periods_per_week=4,
            )
        self.assertEqual(CourseRequirement.objects.count(), 0)

    def test_elective_group_rejected(self):
        subject = Subject.objects.create(
            institution=self.school, department=self.department, name="Mathematics", code="MATH8"
        )
        elective_group = ElectiveGroup.objects.create(
            institution=self.school, term=self.term, name="Not Allowed In School"
        )
        with self.assertRaises(ValidationError):
            ingest_course_requirement(
                institution=self.school, term=self.term, class_division=self.division, subject=subject,
                periods_per_week=4, elective_group=elective_group,
            )
        self.assertEqual(CourseRequirement.objects.count(), 0)

    def test_ingest_is_idempotent_upsert(self):
        subject = Subject.objects.create(
            institution=self.school, department=self.department, name="Mathematics", code="MATH8"
        )
        ingest_course_requirement(
            institution=self.school, term=self.term, class_division=self.division, subject=subject,
            periods_per_week=6, teacher=self.teacher,
        )
        ingest_course_requirement(
            institution=self.school, term=self.term, class_division=self.division, subject=subject,
            periods_per_week=8, teacher=self.teacher,
        )
        self.assertEqual(CourseRequirement.objects.count(), 1)
        self.assertEqual(CourseRequirement.objects.get().periods_per_week, 8)

    def test_cross_tenant_subject_rejected(self):
        other_school = Institution.objects.create(name="Other School", institution_type=Institution.SCHOOL)
        other_department = Department.objects.get(institution=other_school, name="General")
        foreign_subject = Subject.objects.create(
            institution=other_school, department=other_department, name="Mathematics", code="MATH8"
        )
        with self.assertRaises(ValidationError):
            ingest_course_requirement(
                institution=self.school, term=self.term, class_division=self.division,
                subject=foreign_subject, periods_per_week=6,
            )


class IngestCourseRequirementCollegeTests(TestCase):
    """College-mode rules: electives allowed; lab block_size must fit evenly."""

    def setUp(self):
        self.college = Institution.objects.create(
            name="Coromandel Institute of Engineering", institution_type=Institution.COLLEGE, cycle_length=6
        )
        self.department = Department.objects.create(institution=self.college, name="Computer Science")
        self.term = AcademicTerm.objects.create(
            institution=self.college, name="Odd Semester 2026-27",
            start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2026, 11, 30),
        )
        self.division = ClassDivision.objects.create(
            institution=self.college, department=self.department, name="B.Tech CSE III Year", section="A"
        )
        self.teacher = Teacher.objects.create(
            institution=self.college, name="Dr. Lakshmi Venkat", email="lakshmi@coromandel.edu",
            max_periods_per_day=5, max_periods_per_week=24,
        )

    def test_elective_requirement_succeeds(self):
        elective_subject = Subject.objects.create(
            institution=self.college, department=self.department, name="Open Elective - AI Basics",
            code="OE501A", is_elective=True,
        )
        elective_group = ElectiveGroup.objects.create(
            institution=self.college, term=self.term, name="Open Elective Pool - Sem 5"
        )
        req = ingest_course_requirement(
            institution=self.college, term=self.term, class_division=self.division, subject=elective_subject,
            periods_per_week=2, teacher=self.teacher, elective_group=elective_group,
        )
        self.assertEqual(req.elective_group, elective_group)

    def test_lab_block_size_evenly_dividing_succeeds(self):
        lab_subject = Subject.objects.create(
            institution=self.college, department=self.department, name="Data Structures Lab", code="CSE301L"
        )
        req = ingest_course_requirement(
            institution=self.college, term=self.term, class_division=self.division, subject=lab_subject,
            periods_per_week=6, teacher=self.teacher, is_lab=True, block_size=3,
        )
        self.assertEqual(req.block_size, 3)

    def test_lab_block_size_not_dividing_evenly_rejected(self):
        lab_subject = Subject.objects.create(
            institution=self.college, department=self.department, name="Data Structures Lab", code="CSE301L"
        )
        with self.assertRaises(ValidationError):
            ingest_course_requirement(
                institution=self.college, term=self.term, class_division=self.division, subject=lab_subject,
                periods_per_week=5, teacher=self.teacher, is_lab=True, block_size=2,
            )
        self.assertEqual(CourseRequirement.objects.count(), 0)

    def test_lab_block_size_exceeding_periods_rejected(self):
        lab_subject = Subject.objects.create(
            institution=self.college, department=self.department, name="Data Structures Lab", code="CSE301L"
        )
        with self.assertRaises(ValidationError):
            ingest_course_requirement(
                institution=self.college, term=self.term, class_division=self.division, subject=lab_subject,
                periods_per_week=2, teacher=self.teacher, is_lab=True, block_size=3,
            )
