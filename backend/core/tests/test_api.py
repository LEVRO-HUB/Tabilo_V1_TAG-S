import datetime

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core.models import (
    AcademicCalendarDay,
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    Institution,
    SolverRun,
    Subject,
    Substitution,
    Teacher,
    TeacherSubjectEligibility,
    TimeGridConfig,
    TimetableCell,
    UserProfile,
)
from core.services.timegrid import generate_time_slots
from core.solver.apply import apply_solution
from core.solver.build import solve_feasibility


class ApiTestCase(APITestCase):
    """Fixture-building helpers, same style as core/tests/test_solver.py."""

    def make_institution(self, name, cycle_length=3):
        return Institution.objects.create(name=name, institution_type=Institution.COLLEGE, cycle_length=cycle_length)

    def make_grid(self, institution, periods_per_day=4):
        TimeGridConfig.objects.create(
            institution=institution, periods_per_day=periods_per_day, period_duration_minutes=60,
            day_start_time=datetime.time(9, 0), breaks=[{"after_period": 2, "duration_minutes": 15}],
        )
        return generate_time_slots(institution)

    def make_term(self, institution, name="Term"):
        return AcademicTerm.objects.create(
            institution=institution, name=name,
            start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 3, 31),
        )

    def make_user(self, institution, username, role=UserProfile.ADMIN, password="testpass123"):
        User = get_user_model()
        user = User.objects.create_user(username=username, password=password)
        UserProfile.objects.create(user=user, institution=institution, role=role)
        return user

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")


class LoginTests(ApiTestCase):
    def test_valid_credentials_return_token_and_institution_info(self):
        institution = self.make_institution("Test Institution")
        self.make_user(institution, "admin1", role=UserProfile.ADMIN, password="testpass123")

        response = self.client.post(
            "/api/auth/login/", {"username": "admin1", "password": "testpass123"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertTrue(response.data["token"])
        self.assertEqual(response.data["username"], "admin1")
        self.assertEqual(response.data["role"], UserProfile.ADMIN)
        self.assertEqual(response.data["institution"]["id"], institution.id)
        self.assertEqual(response.data["institution"]["name"], institution.name)

    def test_invalid_credentials_return_400_not_a_server_error(self):
        institution = self.make_institution("Test Institution")
        self.make_user(institution, "admin1", password="testpass123")

        response = self.client.post(
            "/api/auth/login/", {"username": "admin1", "password": "wrongpassword"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_username_returns_400(self):
        response = self.client.post(
            "/api/auth/login/", {"username": "nobody", "password": "whatever"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AuthenticationRequiredTests(ApiTestCase):
    def test_endpoints_require_authentication(self):
        for url in ("/api/terms/", "/api/class-divisions/", "/api/timetable-grid/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED, url)


class InstitutionScopingTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.make_grid(self.institution_a)
        self.term_a = self.make_term(self.institution_a, "Term A")
        dept_a = Department.objects.create(institution=self.institution_a, name="Dept A")
        self.division_a = ClassDivision.objects.create(
            institution=self.institution_a, department=dept_a, name="Div A", section="A"
        )

        self.institution_b = self.make_institution("Institution B")
        self.make_grid(self.institution_b)
        self.term_b = self.make_term(self.institution_b, "Term B")
        dept_b = Department.objects.create(institution=self.institution_b, name="Dept B")
        self.division_b = ClassDivision.objects.create(
            institution=self.institution_b, department=dept_b, name="Div B", section="A"
        )

        self.user_a = self.make_user(self.institution_a, "user_a")
        self.authenticate(self.user_a)

    def test_user_with_no_profile_gets_403(self):
        User = get_user_model()
        bare_user = User.objects.create_user(username="bare", password="testpass123")
        self.authenticate(bare_user)

        response = self.client.get("/api/terms/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_terms_list_only_returns_own_institution(self):
        response = self.client.get("/api/terms/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["id"] for row in response.data}, {self.term_a.id})

    def test_class_divisions_list_only_returns_own_institution(self):
        response = self.client.get("/api/class-divisions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["id"] for row in response.data}, {self.division_a.id})

    def test_grid_with_another_institutions_term_id_returns_404(self):
        response = self.client.get(
            f"/api/timetable-grid/?term_id={self.term_b.id}&class_division_id={self.division_a.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_grid_with_another_institutions_class_division_id_returns_404(self):
        response = self.client.get(
            f"/api/timetable-grid/?term_id={self.term_a.id}&class_division_id={self.division_b.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MissingQueryParamsTests(ApiTestCase):
    def setUp(self):
        self.institution = self.make_institution("Test Institution")
        self.make_grid(self.institution)
        self.term = self.make_term(self.institution)
        department = Department.objects.create(institution=self.institution, name="Dept")
        self.division = ClassDivision.objects.create(
            institution=self.institution, department=department, name="Div", section="A"
        )
        self.authenticate(self.make_user(self.institution, "u1"))

    def test_missing_term_id_returns_400(self):
        response = self.client.get(f"/api/timetable-grid/?class_division_id={self.division.id}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_class_division_id_returns_400(self):
        response = self.client.get(f"/api/timetable-grid/?term_id={self.term.id}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_both_returns_400(self):
        response = self.client.get("/api/timetable-grid/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TimetableGridContentTests(ApiTestCase):
    def test_grid_includes_breaks_and_attaches_cells_only_where_solved(self):
        institution = self.make_institution("Grid Test Institution")
        slots = self.make_grid(institution, periods_per_day=4)
        term = self.make_term(institution)
        department = Department.objects.create(institution=institution, name="Dept")
        division = ClassDivision.objects.create(
            institution=institution, department=department, name="Div A", section="A"
        )
        subject = Subject.objects.create(institution=institution, department=department, name="Math", code="MATH1")
        teacher = Teacher.objects.create(
            institution=institution, name="Teacher One", email="t1@test.edu",
            max_periods_per_day=10, max_periods_per_week=40,
        )
        CourseRequirement.objects.create(
            institution=institution, term=term, class_division=division, subject=subject,
            teacher=teacher, periods_per_week=2,
        )

        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)

        self.authenticate(self.make_user(institution, "grid_user"))
        response = self.client.get(
            f"/api/timetable-grid/?term_id={term.id}&class_division_id={division.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data

        self.assertEqual(data["institution"]["id"], institution.id)
        self.assertEqual(data["term"]["id"], term.id)
        self.assertEqual(data["term"]["name"], term.name)
        self.assertEqual(data["class_division"]["id"], division.id)
        self.assertEqual(data["class_division"]["section"], "A")
        self.assertEqual(len(data["slots"]), len(slots))

        break_slots = [s for s in data["slots"] if s["is_break"]]
        self.assertTrue(len(break_slots) > 0)
        self.assertTrue(all(s["cell"] is None for s in break_slots))

        occupied_slots = [s for s in data["slots"] if s["cell"] is not None]
        self.assertEqual(len(occupied_slots), 2)
        for slot in occupied_slots:
            self.assertEqual(slot["cell"]["subject"], "Math")
            self.assertEqual(slot["cell"]["teacher"], "Teacher One")
            self.assertFalse(slot["cell"]["is_locked"])
            self.assertIsNone(slot["cell"]["elective_group_id"])

        empty_non_break_slots = [
            s for s in data["slots"] if s["cell"] is None and not s["is_break"]
        ]
        self.assertEqual(len(empty_non_break_slots), len(slots) - len(break_slots) - 2)

        actual_cell_count = TimetableCell.objects.filter(term=term, class_division=division).count()
        self.assertEqual(actual_cell_count, 2)


class SolverRunTriggerTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.term_a = self.make_term(self.institution_a, "Term A")
        self.institution_b = self.make_institution("Institution B")
        self.term_b = self.make_term(self.institution_b, "Term B")

        self.user_a = self.make_user(self.institution_a, "user_a")
        self.authenticate(self.user_a)

    def test_trigger_returns_202_with_id_and_status(self):
        response = self.client.post("/api/solver-runs/", {"term_id": self.term_a.id}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(set(response.data.keys()), {"id", "status"})

        solver_run = SolverRun.objects.get(pk=response.data["id"])
        self.assertEqual(solver_run.institution_id, self.institution_a.id)
        self.assertEqual(solver_run.term_id, self.term_a.id)
        self.assertEqual(solver_run.trigger, SolverRun.MANUAL)
        self.assertTrue(solver_run.celery_task_id)

    def test_trigger_with_another_institutions_term_id_returns_404(self):
        response = self.client.post("/api/solver-runs/", {"term_id": self.term_b.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(SolverRun.objects.filter(term=self.term_b).exists())

    def test_trigger_without_term_id_returns_400(self):
        response = self.client.post("/api/solver-runs/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_trigger_requires_authentication(self):
        self.client.credentials()
        response = self.client.post("/api/solver-runs/", {"term_id": self.term_a.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SolverRunDetailTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.term_a = self.make_term(self.institution_a, "Term A")
        self.institution_b = self.make_institution("Institution B")
        self.term_b = self.make_term(self.institution_b, "Term B")

        self.user_a = self.make_user(self.institution_a, "user_a")
        self.authenticate(self.user_a)

    def test_detail_returns_expected_fields(self):
        solver_run = SolverRun.objects.create(
            institution=self.institution_a, term=self.term_a, trigger=SolverRun.MANUAL,
            status=SolverRun.SUCCESS, objective_value=12.5,
        )

        response = self.client.get(f"/api/solver-runs/{solver_run.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data.keys()),
            {"id", "status", "trigger", "objective_value", "error_message", "created_at", "started_at", "finished_at"},
        )
        self.assertEqual(response.data["id"], solver_run.id)
        self.assertEqual(response.data["status"], SolverRun.SUCCESS)
        self.assertEqual(response.data["trigger"], SolverRun.MANUAL)
        self.assertEqual(response.data["objective_value"], 12.5)

    def test_detail_for_another_institutions_solver_run_returns_404(self):
        solver_run = SolverRun.objects.create(
            institution=self.institution_b, term=self.term_b, trigger=SolverRun.MANUAL,
        )

        response = self.client.get(f"/api/solver-runs/{solver_run.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_requires_authentication(self):
        solver_run = SolverRun.objects.create(
            institution=self.institution_a, term=self.term_a, trigger=SolverRun.MANUAL,
        )
        self.client.credentials()

        response = self.client.get(f"/api/solver-runs/{solver_run.id}/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DepartmentListTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.department_a = Department.objects.create(institution=self.institution_a, name="Dept A")
        self.institution_b = self.make_institution("Institution B")
        Department.objects.create(institution=self.institution_b, name="Dept B")

    def test_admin_sees_only_own_institution_departments(self):
        self.authenticate(self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN))
        response = self.client.get("/api/departments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({row["id"] for row in response.data}, {self.department_a.id})

    def test_teacher_role_gets_403(self):
        self.authenticate(self.make_user(self.institution_a, "teacher_a", role=UserProfile.TEACHER))
        response = self.client.get("/api/departments/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TeacherManagementTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.institution_b = self.make_institution("Institution B")
        self.admin_a = self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN)
        self.coordinator_a = self.make_user(self.institution_a, "coord_a", role=UserProfile.COORDINATOR)
        self.teacher_role_user = self.make_user(self.institution_a, "teacher_role_a", role=UserProfile.TEACHER)

    def test_admin_can_create_teacher_with_institution_auto_stamped(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/teachers/",
            {"name": "Anita Raman", "email": "anita@test.edu", "max_periods_per_day": 6, "max_periods_per_week": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        teacher = Teacher.objects.get(pk=response.data["id"])
        self.assertEqual(teacher.institution_id, self.institution_a.id)
        self.assertEqual(teacher.is_active, True)

    def test_coordinator_can_also_create_teacher(self):
        self.authenticate(self.coordinator_a)
        response = self.client.post(
            "/api/teachers/",
            {"name": "Suresh Kumar", "email": "suresh@test.edu", "max_periods_per_day": 6, "max_periods_per_week": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_teacher_role_gets_403_on_list_and_create(self):
        self.authenticate(self.teacher_role_user)
        list_response = self.client.get("/api/teachers/")
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

        create_response = self.client.post(
            "/api/teachers/",
            {"name": "X", "email": "x@test.edu", "max_periods_per_day": 6, "max_periods_per_week": 30},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Teacher.objects.filter(email="x@test.edu").exists())

    def test_duplicate_email_returns_clean_400(self):
        self.authenticate(self.admin_a)
        Teacher.objects.create(
            institution=self.institution_a, name="Anita Raman", email="dup@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        response = self.client.post(
            "/api/teachers/",
            {"name": "Someone Else", "email": "dup@test.edu", "max_periods_per_day": 6, "max_periods_per_week": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["detail"])
        self.assertEqual(Teacher.objects.filter(email="dup@test.edu").count(), 1)

    def test_detail_for_another_institutions_teacher_returns_404(self):
        foreign_teacher = Teacher.objects.create(
            institution=self.institution_b, name="Foreign Teacher", email="foreign@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/teachers/{foreign_teacher.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_deactivates_without_deleting_or_touching_other_data(self):
        term = self.make_term(self.institution_a)
        self.make_grid(self.institution_a)
        department = Department.objects.create(institution=self.institution_a, name="Dept")
        division = ClassDivision.objects.create(
            institution=self.institution_a, department=department, name="Div", section="A"
        )
        subject = Subject.objects.create(institution=self.institution_a, department=department, name="Math", code="M1")
        teacher = Teacher.objects.create(
            institution=self.institution_a, name="Anita Raman", email="anita2@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        CourseRequirement.objects.create(
            institution=self.institution_a, term=term, class_division=division, subject=subject,
            teacher=teacher, periods_per_week=2,
        )
        result = solve_feasibility(term)
        self.assertEqual(result.status, "FEASIBLE")
        apply_solution(term, result.assignments)
        cells_before = TimetableCell.objects.filter(term=term).count()
        self.assertTrue(cells_before > 0)

        self.authenticate(self.admin_a)
        response = self.client.patch(f"/api/teachers/{teacher.id}/", {"is_active": False}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["is_active"], False)

        teacher.refresh_from_db()
        self.assertFalse(teacher.is_active)
        self.assertTrue(Teacher.objects.filter(pk=teacher.pk).exists())
        self.assertEqual(CourseRequirement.objects.filter(teacher=teacher).count(), 1)
        self.assertEqual(TimetableCell.objects.filter(term=term).count(), cells_before)


class SubjectManagementTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.department_a = Department.objects.create(institution=self.institution_a, name="Dept A")
        self.institution_b = self.make_institution("Institution B")
        self.department_b = Department.objects.create(institution=self.institution_b, name="Dept B")
        self.admin_a = self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN)
        self.teacher_role_user = self.make_user(self.institution_a, "teacher_role_a", role=UserProfile.TEACHER)

    def test_admin_can_create_subject(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/subjects/",
            {"name": "Mathematics", "code": "MATH8", "department": self.department_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        subject = Subject.objects.get(pk=response.data["id"])
        self.assertEqual(subject.institution_id, self.institution_a.id)

    def test_teacher_role_gets_403(self):
        self.authenticate(self.teacher_role_user)
        response = self.client.post(
            "/api/subjects/",
            {"name": "Mathematics", "code": "MATH8", "department": self.department_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_department_from_another_institution_returns_404(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/subjects/",
            {"name": "Mathematics", "code": "MATH8", "department": self.department_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Subject.objects.filter(code="MATH8").exists())

    def test_duplicate_code_returns_clean_400(self):
        Subject.objects.create(institution=self.institution_a, department=self.department_a, name="Math", code="DUP1")
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/subjects/",
            {"name": "Math Again", "code": "DUP1", "department": self.department_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["detail"])

    def test_delete_is_a_real_hard_delete(self):
        subject = Subject.objects.create(
            institution=self.institution_a, department=self.department_a, name="Math", code="DEL1"
        )
        self.authenticate(self.admin_a)
        response = self.client.delete(f"/api/subjects/{subject.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Subject.objects.filter(pk=subject.id).exists())

    def test_detail_for_another_institutions_subject_returns_404(self):
        foreign_subject = Subject.objects.create(
            institution=self.institution_b, department=self.department_b, name="Foreign", code="FOR1"
        )
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/subjects/{foreign_subject.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CourseRequirementManagementTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.term_a = self.make_term(self.institution_a)
        self.department_a = Department.objects.create(institution=self.institution_a, name="Dept A")
        self.division_a = ClassDivision.objects.create(
            institution=self.institution_a, department=self.department_a, name="Div A", section="A"
        )
        self.subject_a = Subject.objects.create(
            institution=self.institution_a, department=self.department_a, name="Math", code="MATH1"
        )
        self.teacher_a = Teacher.objects.create(
            institution=self.institution_a, name="Anita Raman", email="anita3@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )

        self.institution_b = self.make_institution("Institution B")
        self.term_b = self.make_term(self.institution_b, "Term B")

        self.admin_a = self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN)
        self.teacher_role_user = self.make_user(self.institution_a, "teacher_role_a", role=UserProfile.TEACHER)

    def test_admin_can_create_course_requirement(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/course-requirements/",
            {
                "term": self.term_a.id, "class_division": self.division_a.id, "subject": self.subject_a.id,
                "teacher": self.teacher_a.id, "periods_per_week": 4,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["subject_name"], "Math")
        self.assertEqual(response.data["class_division_name"], "Div A - A")
        self.assertEqual(response.data["teacher_name"], "Anita Raman")
        self.assertEqual(CourseRequirement.objects.count(), 1)

    def test_create_with_no_teacher_leaves_it_null(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/course-requirements/",
            {"term": self.term_a.id, "class_division": self.division_a.id, "subject": self.subject_a.id, "periods_per_week": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["teacher"])
        self.assertIsNone(response.data["teacher_name"])

    def test_teacher_role_gets_403(self):
        self.authenticate(self.teacher_role_user)
        response = self.client.post(
            "/api/course-requirements/",
            {"term": self.term_a.id, "class_division": self.division_a.id, "subject": self.subject_a.id, "periods_per_week": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_term_returns_404(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/course-requirements/",
            {"term": self.term_b.id, "class_division": self.division_a.id, "subject": self.subject_a.id, "periods_per_week": 4},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(CourseRequirement.objects.count(), 0)

    def test_school_institution_electives_rejected_with_real_service_message(self):
        """Proves the view delegates to ingest_course_requirement for real,
        not just that some 400 comes back for an unrelated reason -- this
        is the School vs. College rule enforced only inside the service."""
        school = Institution.objects.create(
            name="Greenwood School", institution_type=Institution.SCHOOL, cycle_length=6
        )
        school_department = Department.objects.get(institution=school, name="General")
        school_term = self.make_term(school, "Annual 2026")
        school_division = ClassDivision.objects.create(
            institution=school, department=school_department, name="Grade 8", section="A"
        )
        elective_subject = Subject.objects.create(
            institution=school, department=school_department, name="Art Elective", code="ART8", is_elective=True,
        )
        self.authenticate(self.make_user(school, "school_admin", role=UserProfile.ADMIN))

        response = self.client.post(
            "/api/course-requirements/",
            {
                "term": school_term.id, "class_division": school_division.id, "subject": elective_subject.id,
                "periods_per_week": 4,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("School institutions cannot carry an elective", response.data["detail"])
        self.assertEqual(CourseRequirement.objects.count(), 0)

    def test_patch_updates_periods_per_week_via_service(self):
        course_requirement = CourseRequirement.objects.create(
            institution=self.institution_a, term=self.term_a, class_division=self.division_a,
            subject=self.subject_a, teacher=self.teacher_a, periods_per_week=2,
        )
        self.authenticate(self.admin_a)
        response = self.client.patch(
            f"/api/course-requirements/{course_requirement.id}/", {"periods_per_week": 5}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        course_requirement.refresh_from_db()
        self.assertEqual(course_requirement.periods_per_week, 5)

    def test_patch_with_invalid_lab_block_size_returns_service_message(self):
        course_requirement = CourseRequirement.objects.create(
            institution=self.institution_a, term=self.term_a, class_division=self.division_a,
            subject=self.subject_a, teacher=self.teacher_a, periods_per_week=5,
        )
        self.authenticate(self.admin_a)
        response = self.client.patch(
            f"/api/course-requirements/{course_requirement.id}/",
            {"is_lab": True, "block_size": 2},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must evenly divide", response.data["detail"])
        course_requirement.refresh_from_db()
        self.assertFalse(course_requirement.is_lab)

    def test_delete_is_a_real_hard_delete(self):
        course_requirement = CourseRequirement.objects.create(
            institution=self.institution_a, term=self.term_a, class_division=self.division_a,
            subject=self.subject_a, teacher=self.teacher_a, periods_per_week=2,
        )
        self.authenticate(self.admin_a)
        response = self.client.delete(f"/api/course-requirements/{course_requirement.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CourseRequirement.objects.filter(pk=course_requirement.id).exists())

    def test_detail_for_another_institutions_course_requirement_returns_404(self):
        department_b = Department.objects.create(institution=self.institution_b, name="Dept B")
        division_b = ClassDivision.objects.create(
            institution=self.institution_b, department=department_b, name="Div B", section="A"
        )
        subject_b = Subject.objects.create(
            institution=self.institution_b, department=department_b, name="Physics", code="PHY1"
        )
        foreign_requirement = CourseRequirement.objects.create(
            institution=self.institution_b, term=self.term_b, class_division=division_b,
            subject=subject_b, periods_per_week=3,
        )
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/course-requirements/{foreign_requirement.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ResignationRecoveryTriggerTests(ApiTestCase):
    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.term_a = self.make_term(self.institution_a, "Term A")
        self.resigned_teacher_a = Teacher.objects.create(
            institution=self.institution_a, name="Resigned Teacher", email="resigned@test.edu",
            max_periods_per_day=6, max_periods_per_week=30, is_active=False,
        )
        self.active_teacher_a = Teacher.objects.create(
            institution=self.institution_a, name="Active Teacher", email="active@test.edu",
            max_periods_per_day=6, max_periods_per_week=30, is_active=True,
        )

        self.institution_b = self.make_institution("Institution B")
        self.term_b = self.make_term(self.institution_b, "Term B")
        self.resigned_teacher_b = Teacher.objects.create(
            institution=self.institution_b, name="Foreign Resigned Teacher", email="foreign@test.edu",
            max_periods_per_day=6, max_periods_per_week=30, is_active=False,
        )

        self.admin_a = self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN)
        self.teacher_role_user = self.make_user(self.institution_a, "teacher_role_a", role=UserProfile.TEACHER)

    def test_trigger_returns_202_with_real_resignation_recovery_solver_run(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.resigned_teacher_a.id, "term_id": self.term_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(set(response.data.keys()), {"id", "status"})

        solver_run = SolverRun.objects.get(pk=response.data["id"])
        self.assertEqual(solver_run.trigger, SolverRun.RESIGNATION_RECOVERY)
        self.assertEqual(solver_run.institution_id, self.institution_a.id)
        self.assertEqual(solver_run.term_id, self.term_a.id)
        self.assertTrue(solver_run.celery_task_id)

    def test_still_active_teacher_returns_clean_400_without_side_effects(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.active_teacher_a.id, "term_id": self.term_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("resigned", response.data["detail"])
        self.assertEqual(SolverRun.objects.count(), 0)

    def test_teacher_role_gets_403_without_side_effects(self):
        self.authenticate(self.teacher_role_user)
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.resigned_teacher_a.id, "term_id": self.term_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(SolverRun.objects.count(), 0)

    def test_foreign_teacher_id_returns_404_without_side_effects(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.resigned_teacher_b.id, "term_id": self.term_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(SolverRun.objects.count(), 0)

    def test_foreign_term_id_returns_404_without_side_effects(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.resigned_teacher_a.id, "term_id": self.term_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(SolverRun.objects.count(), 0)

    def test_missing_fields_returns_400(self):
        self.authenticate(self.admin_a)
        response = self.client.post("/api/resignation-recovery/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(SolverRun.objects.count(), 0)

    def test_requires_authentication(self):
        response = self.client.post(
            "/api/resignation-recovery/",
            {"teacher_id": self.resigned_teacher_a.id, "term_id": self.term_a.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SubstitutionApiTestCase(ApiTestCase):
    """Shared fixture for the three Phase 8 endpoints: an institution with
    a real cell on a specific calendar date."""

    DATE = datetime.date(2026, 8, 3)

    def setUp(self):
        self.institution_a = self.make_institution("Institution A")
        self.slots = self.make_grid(self.institution_a, periods_per_day=3)
        AcademicCalendarDay.objects.create(institution=self.institution_a, date=self.DATE, day_identifier=1)
        self.term_a = self.make_term(self.institution_a, "Term A")
        self.term_a.is_active = True
        self.term_a.save(update_fields=["is_active"])
        self.department_a = Department.objects.create(institution=self.institution_a, name="Dept A")
        self.division_a = ClassDivision.objects.create(
            institution=self.institution_a, department=self.department_a, name="Div A", section="A"
        )
        self.subject_a = Subject.objects.create(
            institution=self.institution_a, department=self.department_a, name="Math", code="MATH1"
        )
        self.original_teacher = Teacher.objects.create(
            institution=self.institution_a, name="Original Teacher", email="original@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        self.replacement_teacher = Teacher.objects.create(
            institution=self.institution_a, name="Replacement Teacher", email="replacement@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        self.slot_day1_period1 = next(s for s in self.slots if s.day_identifier == 1 and s.period_number == 1)
        self.cell = TimetableCell.objects.create(
            institution=self.institution_a, term=self.term_a, class_division=self.division_a,
            time_slot=self.slot_day1_period1, subject=self.subject_a, teacher=self.original_teacher,
        )

        self.institution_b = self.make_institution("Institution B")
        self.admin_a = self.make_user(self.institution_a, "admin_a", role=UserProfile.ADMIN)
        self.teacher_role_user = self.make_user(self.institution_a, "teacher_role_a", role=UserProfile.TEACHER)


class SubstitutionSuggestionsApiTests(SubstitutionApiTestCase):
    def test_admin_gets_ranked_suggestions(self):
        TeacherSubjectEligibility.objects.create(
            institution=self.institution_a, teacher=self.replacement_teacher, subject=self.subject_a
        )
        self.authenticate(self.admin_a)
        response = self.client.get(
            f"/api/substitution-suggestions/?cell_id={self.cell.id}&date={self.DATE.isoformat()}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        candidate_ids = [c["teacher_id"] for c in response.data["candidates"]]
        self.assertIn(self.replacement_teacher.id, candidate_ids)
        self.assertNotIn(self.original_teacher.id, candidate_ids)

    def test_teacher_role_gets_403(self):
        self.authenticate(self.teacher_role_user)
        response = self.client.get(
            f"/api/substitution-suggestions/?cell_id={self.cell.id}&date={self.DATE.isoformat()}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_foreign_cell_id_returns_404(self):
        department_b = Department.objects.create(institution=self.institution_b, name="Dept B")
        division_b = ClassDivision.objects.create(
            institution=self.institution_b, department=department_b, name="Div B", section="A"
        )
        subject_b = Subject.objects.create(
            institution=self.institution_b, department=department_b, name="Physics", code="PHY1"
        )
        teacher_b = Teacher.objects.create(
            institution=self.institution_b, name="Teacher B", email="teacherb@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        slots_b = self.make_grid(self.institution_b, periods_per_day=3)
        cell_b = TimetableCell.objects.create(
            institution=self.institution_b, term=self.make_term(self.institution_b, "Term B"),
            class_division=division_b, time_slot=slots_b[0], subject=subject_b, teacher=teacher_b,
        )
        self.authenticate(self.admin_a)
        response = self.client.get(
            f"/api/substitution-suggestions/?cell_id={cell_b.id}&date={self.DATE.isoformat()}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_params_returns_400(self):
        self.authenticate(self.admin_a)
        response = self.client.get("/api/substitution-suggestions/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_working_day_returns_400_with_real_reason(self):
        self.authenticate(self.admin_a)
        off_date = self.DATE + datetime.timedelta(days=100)
        response = self.client.get(
            f"/api/substitution-suggestions/?cell_id={self.cell.id}&date={off_date.isoformat()}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("calendar entry", response.data["detail"])


class SubstitutionCreateApiTests(SubstitutionApiTestCase):
    def test_admin_can_record_a_substitution(self):
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/substitutions/",
            {
                "cell_id": self.cell.id, "date": self.DATE.isoformat(),
                "substitute_teacher_id": self.replacement_teacher.id, "reason": "Sick",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["substitute_teacher_name"], "Replacement Teacher")
        self.assertEqual(Substitution.objects.count(), 1)

    def test_teacher_role_gets_403_without_side_effects(self):
        self.authenticate(self.teacher_role_user)
        response = self.client.post(
            "/api/substitutions/",
            {"cell_id": self.cell.id, "date": self.DATE.isoformat(), "substitute_teacher_id": self.replacement_teacher.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Substitution.objects.count(), 0)

    def test_invalid_substitute_returns_clean_400_not_500(self):
        # original_teacher is themself excluded -- they're the cell's own teacher.
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/substitutions/",
            {"cell_id": self.cell.id, "date": self.DATE.isoformat(), "substitute_teacher_id": self.original_teacher.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Substitution.objects.count(), 0)

    def test_foreign_substitute_teacher_id_returns_404(self):
        teacher_b = Teacher.objects.create(
            institution=self.institution_b, name="Teacher B", email="teacherb2@test.edu",
            max_periods_per_day=6, max_periods_per_week=30,
        )
        self.authenticate(self.admin_a)
        response = self.client.post(
            "/api/substitutions/",
            {"cell_id": self.cell.id, "date": self.DATE.isoformat(), "substitute_teacher_id": teacher_b.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_authentication(self):
        response = self.client.post(
            "/api/substitutions/",
            {"cell_id": self.cell.id, "date": self.DATE.isoformat(), "substitute_teacher_id": self.replacement_teacher.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TodaysScheduleApiTests(SubstitutionApiTestCase):
    def test_admin_sees_schedule_for_date(self):
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/todays-schedule/?date={self.DATE.isoformat()}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_working_day"])
        self.assertEqual(response.data["day_identifier"], 1)
        cell_ids = [c["cell_id"] for c in response.data["cells"]]
        self.assertIn(self.cell.id, cell_ids)

    def test_teacher_role_can_also_read_it(self):
        """Deliberate choice (see TodaysScheduleView's docstring):
        read-only, open to every authenticated role, same as
        timetable-grid -- not gated by ManagedResourceMixin."""
        self.authenticate(self.teacher_role_user)
        response = self.client.get(f"/api/todays-schedule/?date={self.DATE.isoformat()}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_working_day_returns_empty_with_clear_reason(self):
        holiday = self.DATE + datetime.timedelta(days=1)
        AcademicCalendarDay.objects.create(
            institution=self.institution_a, date=holiday, day_identifier=None, is_holiday=True, label="Founders Day"
        )
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/todays-schedule/?date={holiday.isoformat()}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_working_day"])
        self.assertEqual(response.data["cells"], [])
        self.assertEqual(response.data["reason"], "Founders Day")

    def test_reflects_an_existing_substitution(self):
        Substitution.objects.create(
            institution=self.institution_a, term=self.term_a, original_cell=self.cell, date=self.DATE,
            substitute_teacher=self.replacement_teacher, reason="Sick",
        )
        self.authenticate(self.admin_a)
        response = self.client.get(f"/api/todays-schedule/?date={self.DATE.isoformat()}")
        cell_row = next(c for c in response.data["cells"] if c["cell_id"] == self.cell.id)
        self.assertIsNotNone(cell_row["substitution"])
        self.assertEqual(cell_row["substitution"]["substitute_teacher_name"], "Replacement Teacher")

    def test_defaults_to_today_when_date_omitted(self):
        self.authenticate(self.admin_a)
        response = self.client.get("/api/todays-schedule/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_requires_authentication(self):
        response = self.client.get(f"/api/todays-schedule/?date={self.DATE.isoformat()}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
