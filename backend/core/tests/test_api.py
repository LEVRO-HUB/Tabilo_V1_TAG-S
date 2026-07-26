import datetime

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    Institution,
    SolverRun,
    Subject,
    Teacher,
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
