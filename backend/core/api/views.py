"""
Tabilo — REST API views (Phase 5b)

A scoped API: authentication + institution-scoped access, plus one
purpose-built endpoint (TimetableGridView) for the first frontend screen.
Not a full CRUD API yet -- see core/api/permissions.py for the
institution-scoping rules every endpoint here follows.
"""

import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import InstitutionScopedMixin, ManagedResourceMixin
from core.api.serializers import (
    AcademicTermSerializer,
    ClassDivisionSerializer,
    CourseRequirementSerializer,
    DepartmentSerializer,
    InstitutionSerializer,
    SolverRunSerializer,
    SubjectSerializer,
    SubstitutionSerializer,
    TeacherSerializer,
)
from core.models import (
    AcademicCalendarDay,
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    ElectiveGroup,
    SolverRun,
    Subject,
    Substitution,
    Teacher,
    TimeSlot,
    TimetableCell,
)
from core.services.ingestion import ingest_course_requirement
from core.services.substitution import record_substitution, suggest_substitutes
from core.tasks import run_feasibility_solver, run_resignation_recovery


class LoginView(ObtainAuthToken):
    """
    POST /api/auth/login/ {"username": ..., "password": ...}

    Returns a token plus the caller's id/username/role/institution in one
    response, so the frontend has everything it needs right after login
    without a second round trip. Invalid credentials -> clean 400 (DRF's
    default exception handling for a raised serializer ValidationError),
    never a 500.
    """
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)

        profile = getattr(user, "profile", None)
        return Response({
            "token": token.key,
            "user_id": user.id,
            "username": user.username,
            "role": profile.role if profile else None,
            "institution": InstitutionSerializer(profile.institution).data if profile else None,
        })


class TermListView(InstitutionScopedMixin, generics.ListAPIView):
    """GET /api/terms/ -- AcademicTerms for the requester's institution only."""

    serializer_class = AcademicTermSerializer

    def get_queryset(self):
        return self.scope_queryset(AcademicTerm.objects.all()).order_by("-start_date")


class ClassDivisionListView(InstitutionScopedMixin, generics.ListAPIView):
    """GET /api/class-divisions/ -- ClassDivisions for the requester's institution only."""

    serializer_class = ClassDivisionSerializer

    def get_queryset(self):
        return self.scope_queryset(
            ClassDivision.objects.select_related("department")
        ).order_by("name", "section")


class TimetableGridView(InstitutionScopedMixin, APIView):
    """
    GET /api/timetable-grid/?term_id=<id>&class_division_id=<id>

    Every TimeSlot for the institution (including breaks, so the frontend
    can render them as visual gaps without separate logic), each annotated
    with the TimetableCell for the requested class_division+term, or null.
    """

    def get(self, request):
        term_id = request.query_params.get("term_id")
        class_division_id = request.query_params.get("class_division_id")
        if not term_id or not class_division_id:
            return Response(
                {"detail": "Both term_id and class_division_id query parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        term = get_object_or_404(self.scope_queryset(AcademicTerm.objects.all()), pk=term_id)
        class_division = get_object_or_404(
            self.scope_queryset(ClassDivision.objects.all()), pk=class_division_id
        )

        slots = TimeSlot.objects.filter(institution=self.institution).order_by("day_identifier", "period_number")

        # Avoid N+1: one query for every relevant TimetableCell, keyed by
        # time_slot_id, then attach in-memory while iterating slots below --
        # not a per-slot query.
        cells_by_slot_id = {
            cell.time_slot_id: cell
            for cell in TimetableCell.objects.filter(
                term=term, class_division=class_division
            ).select_related("subject", "teacher")
        }

        slots_payload = []
        for slot in slots:
            cell = cells_by_slot_id.get(slot.id)
            slots_payload.append({
                "id": slot.id,
                "day_identifier": slot.day_identifier,
                "period_number": slot.period_number,
                "start_time": slot.start_time,
                "end_time": slot.end_time,
                "is_break": slot.is_break,
                "cell": {
                    "subject": cell.subject.name,
                    "teacher": cell.teacher.name,
                    "is_locked": cell.is_locked,
                    "elective_group_id": cell.elective_group_id,
                } if cell is not None else None,
            })

        return Response({
            "institution": InstitutionSerializer(self.institution).data,
            "term": {"id": term.id, "name": term.name, "is_active": term.is_active},
            "class_division": {
                "id": class_division.id, "name": class_division.name, "section": class_division.section,
            },
            "slots": slots_payload,
        })


class SolverRunTriggerView(InstitutionScopedMixin, APIView):
    """
    POST /api/solver-runs/ {"term_id": <id>, "feasibility_only": false}

    Enqueues core.tasks.run_feasibility_solver as a real Celery task via
    .delay() -- unlike every other caller so far (management commands'
    --sync path, tests), a request from the browser must never block on a
    solve that can take up to SOLVER_TIME_LIMIT_SECONDS. Returns 202 with
    just the SolverRun id/status (not the full result -- it isn't ready
    yet); the frontend polls GET /api/solver-runs/<id>/ for the outcome.
    """

    def post(self, request):
        term_id = request.data.get("term_id")
        if not term_id:
            return Response({"detail": "term_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        feasibility_only = bool(request.data.get("feasibility_only", False))

        term = get_object_or_404(self.scope_queryset(AcademicTerm.objects.all()), pk=term_id)

        solver_run = SolverRun.objects.create(institution=self.institution, term=term, trigger=SolverRun.MANUAL)
        async_result = run_feasibility_solver.delay(term.id, solver_run.id, feasibility_only)
        solver_run.celery_task_id = async_result.id
        solver_run.save(update_fields=["celery_task_id"])

        return Response(
            {"id": solver_run.id, "status": solver_run.status}, status=status.HTTP_202_ACCEPTED,
        )


class SolverRunDetailView(InstitutionScopedMixin, generics.RetrieveAPIView):
    """GET /api/solver-runs/<id>/ -- status of one solver run. Polled by
    the frontend after POST /api/solver-runs/ enqueues a solve."""

    serializer_class = SolverRunSerializer

    def get_queryset(self):
        return self.scope_queryset(SolverRun.objects.all())


# ---------------------------------------------------------------------------
# Phase 6: Teacher / Subject / Course Requirement management
#
# The first views that require IsAdminOrCoordinator (via ManagedResourceMixin)
# on top of institution scoping -- a TEACHER-role user gets a clean 403 with
# ManagedResourceMixin's message, same institution-scoping rules as before.
# ---------------------------------------------------------------------------

class DepartmentListView(ManagedResourceMixin, generics.ListAPIView):
    """GET /api/departments/ -- read-only, populates the Subject form's
    department dropdown. No CRUD for Department in this phase."""

    serializer_class = DepartmentSerializer

    def get_queryset(self):
        return self.scope_queryset(Department.objects.all()).order_by("name")


class TeacherListCreateView(ManagedResourceMixin, APIView):
    """
    GET /api/teachers/ -- list.
    POST /api/teachers/ {"name", "email", "max_periods_per_day",
    "max_periods_per_week", "is_active"} -- create. institution is always
    self.institution, never client-supplied.

    No DELETE anywhere for Teacher -- "deactivating" is PATCH is_active on
    the detail view below, not a delete.
    """

    def get(self, request):
        teachers = self.scope_queryset(Teacher.objects.all()).order_by("name")
        return Response(TeacherSerializer(teachers, many=True).data)

    def post(self, request):
        serializer = TeacherSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                teacher = serializer.save(institution=self.institution)
        except IntegrityError:
            return Response(
                {"detail": "A teacher with this email already exists."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(TeacherSerializer(teacher).data, status=status.HTTP_201_CREATED)


class TeacherDetailView(ManagedResourceMixin, APIView):
    """GET/PATCH /api/teachers/<id>/ -- no PUT, no DELETE. Deactivation is
    PATCH {"is_active": false}; it never touches resignation recovery
    (core/services/resignation.py) -- that stays a separate, explicit
    action in a later phase."""

    def get(self, request, pk):
        teacher = get_object_or_404(self.scope_queryset(Teacher.objects.all()), pk=pk)
        return Response(TeacherSerializer(teacher).data)

    def patch(self, request, pk):
        teacher = get_object_or_404(self.scope_queryset(Teacher.objects.all()), pk=pk)
        serializer = TeacherSerializer(teacher, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            return Response(
                {"detail": "A teacher with this email already exists."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(serializer.data)


class SubjectListCreateView(ManagedResourceMixin, APIView):
    """GET/POST /api/subjects/. department is validated as belonging to
    the requester's institution (not just any Department pk) before
    saving, the same anti-leak standard the course-requirement view below
    applies to its foreign ids."""

    def get(self, request):
        subjects = self.scope_queryset(Subject.objects.select_related("department")).order_by("department", "name")
        return Response(SubjectSerializer(subjects, many=True).data)

    def post(self, request):
        serializer = SubjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        department = get_object_or_404(
            self.scope_queryset(Department.objects.all()), pk=serializer.validated_data["department"].pk
        )
        try:
            with transaction.atomic():
                subject = serializer.save(institution=self.institution, department=department)
        except IntegrityError:
            return Response(
                {"detail": "A subject with this code already exists."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(SubjectSerializer(subject).data, status=status.HTTP_201_CREATED)


class SubjectDetailView(ManagedResourceMixin, APIView):
    """GET/PATCH/DELETE /api/subjects/<id>/ -- DELETE is a real hard
    delete; Subject's FKs from CourseRequirement and TimetableCell are
    both on_delete=CASCADE, so this cleanly removes any dependent rows
    rather than leaving orphans or raising an IntegrityError."""

    def get(self, request, pk):
        subject = get_object_or_404(self.scope_queryset(Subject.objects.all()), pk=pk)
        return Response(SubjectSerializer(subject).data)

    def patch(self, request, pk):
        subject = get_object_or_404(self.scope_queryset(Subject.objects.all()), pk=pk)
        serializer = SubjectSerializer(subject, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        save_kwargs = {}
        if "department" in serializer.validated_data:
            save_kwargs["department"] = get_object_or_404(
                self.scope_queryset(Department.objects.all()), pk=serializer.validated_data["department"].pk
            )
        try:
            with transaction.atomic():
                serializer.save(**save_kwargs)
        except IntegrityError:
            return Response(
                {"detail": "A subject with this code already exists."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(serializer.data)

    def delete(self, request, pk):
        subject = get_object_or_404(self.scope_queryset(Subject.objects.all()), pk=pk)
        subject.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _resolve_course_requirement_field(view, data, field, model, existing_obj):
    """
    Resolve one foreign-key field of a CourseRequirement from request data,
    institution-scoped -- a foreign id from another institution 404s. If
    the field is absent from the request (PATCH may omit it), falls back
    to the existing object's current value so a partial update doesn't
    have to resend every field. Returns None for an explicitly-null
    optional field (teacher, elective_group).
    """
    if field not in data:
        return getattr(existing_obj, field) if existing_obj is not None else None
    raw_value = data.get(field)
    if raw_value in (None, ""):
        return None
    return get_object_or_404(view.scope_queryset(model.objects.all()), pk=raw_value)


class CourseRequirementListCreateView(ManagedResourceMixin, APIView):
    """
    GET/POST /api/course-requirements/. POST delegates to
    core.services.ingestion.ingest_course_requirement -- never a plain
    ModelSerializer.save() -- so School vs. College rules (no electives on
    School, lab block_size must evenly divide periods_per_week) and
    cross-tenant FK checks are enforced in one place, not reimplemented
    here. The service's own ValidationError becomes a clean 400 with its
    real message, not a generic DRF validation shape.
    """

    def get(self, request):
        course_requirements = self.scope_queryset(
            CourseRequirement.objects.select_related("term", "subject", "class_division", "teacher")
        ).order_by("term", "class_division", "subject")
        return Response(CourseRequirementSerializer(course_requirements, many=True).data)

    def post(self, request):
        data = request.data
        for required_field in ("term", "class_division", "subject", "periods_per_week"):
            if not data.get(required_field):
                return Response(
                    {"detail": f"{required_field} is required."}, status=status.HTTP_400_BAD_REQUEST
                )

        term = get_object_or_404(self.scope_queryset(AcademicTerm.objects.all()), pk=data["term"])
        class_division = get_object_or_404(
            self.scope_queryset(ClassDivision.objects.all()), pk=data["class_division"]
        )
        subject = get_object_or_404(self.scope_queryset(Subject.objects.all()), pk=data["subject"])
        teacher = _resolve_course_requirement_field(self, data, "teacher", Teacher, None)
        elective_group = _resolve_course_requirement_field(self, data, "elective_group", ElectiveGroup, None)

        try:
            periods_per_week = int(data["periods_per_week"])
            block_size = int(data.get("block_size", 1))
        except (TypeError, ValueError):
            return Response(
                {"detail": "periods_per_week and block_size must be integers."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                course_requirement = ingest_course_requirement(
                    institution=self.institution,
                    term=term,
                    class_division=class_division,
                    subject=subject,
                    periods_per_week=periods_per_week,
                    teacher=teacher,
                    is_lab=bool(data.get("is_lab", False)),
                    block_size=block_size,
                    elective_group=elective_group,
                )
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"detail": "block_size cannot exceed periods_per_week."}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(CourseRequirementSerializer(course_requirement).data, status=status.HTTP_201_CREATED)


class CourseRequirementDetailView(ManagedResourceMixin, APIView):
    """GET/PATCH/DELETE /api/course-requirements/<id>/. PATCH also
    delegates to ingest_course_requirement (never a bare .save()) --
    unspecified fields fall back to the existing row's current values so a
    partial edit (e.g. just periods_per_week) doesn't have to resend the
    whole form. DELETE is a real hard delete; TimetableCell.course_requirement
    is on_delete=SET_NULL, so existing generated cells survive with the
    link cleared rather than being deleted."""

    def get(self, request, pk):
        course_requirement = get_object_or_404(
            self.scope_queryset(
                CourseRequirement.objects.select_related("term", "subject", "class_division", "teacher")
            ),
            pk=pk,
        )
        return Response(CourseRequirementSerializer(course_requirement).data)

    def patch(self, request, pk):
        course_requirement = get_object_or_404(self.scope_queryset(CourseRequirement.objects.all()), pk=pk)
        data = request.data

        term = _resolve_course_requirement_field(self, data, "term", AcademicTerm, course_requirement)
        class_division = _resolve_course_requirement_field(
            self, data, "class_division", ClassDivision, course_requirement
        )
        subject = _resolve_course_requirement_field(self, data, "subject", Subject, course_requirement)
        teacher = _resolve_course_requirement_field(self, data, "teacher", Teacher, course_requirement)
        elective_group = _resolve_course_requirement_field(
            self, data, "elective_group", ElectiveGroup, course_requirement
        )

        try:
            periods_per_week = int(data.get("periods_per_week", course_requirement.periods_per_week))
            block_size = int(data.get("block_size", course_requirement.block_size))
        except (TypeError, ValueError):
            return Response(
                {"detail": "periods_per_week and block_size must be integers."}, status=status.HTTP_400_BAD_REQUEST
            )
        is_lab = bool(data.get("is_lab", course_requirement.is_lab))

        try:
            with transaction.atomic():
                updated = ingest_course_requirement(
                    institution=self.institution,
                    term=term,
                    class_division=class_division,
                    subject=subject,
                    periods_per_week=periods_per_week,
                    teacher=teacher,
                    is_lab=is_lab,
                    block_size=block_size,
                    elective_group=elective_group,
                )
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"detail": "block_size cannot exceed periods_per_week."}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(CourseRequirementSerializer(updated).data)

    def delete(self, request, pk):
        course_requirement = get_object_or_404(self.scope_queryset(CourseRequirement.objects.all()), pk=pk)
        course_requirement.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Phase 7: resignation recovery trigger
# ---------------------------------------------------------------------------

class ResignationRecoveryTriggerView(ManagedResourceMixin, APIView):
    """
    POST /api/resignation-recovery/ {"teacher_id": <id>, "term_id": <id>}

    Same trigger-then-poll shape as SolverRunTriggerView (Phase 5d):
    enqueues core.tasks.run_resignation_recovery via .delay() and returns
    202 with just {id, status} -- the frontend polls the EXISTING
    GET /api/solver-runs/<id>/ for the outcome, no new GET endpoint needed.
    ADMIN/COORDINATOR only (ManagedResourceMixin), same as every other
    Phase 6 management endpoint.

    The still-active precondition is checked here, before enqueuing --
    core.services.resignation.recover_from_resignation also enforces it
    (raising ValueError), but failing fast here means a doomed request
    never reaches a worker or creates a SolverRun row at all.
    """

    def post(self, request):
        teacher_id = request.data.get("teacher_id")
        term_id = request.data.get("term_id")
        if not teacher_id or not term_id:
            return Response(
                {"detail": "teacher_id and term_id are required."}, status=status.HTTP_400_BAD_REQUEST
            )

        teacher = get_object_or_404(self.scope_queryset(Teacher.objects.all()), pk=teacher_id)
        term = get_object_or_404(self.scope_queryset(AcademicTerm.objects.all()), pk=term_id)

        if teacher.is_active:
            return Response(
                {"detail": "Teacher must be marked as resigned first."}, status=status.HTTP_400_BAD_REQUEST
            )

        solver_run = SolverRun.objects.create(
            institution=self.institution, term=term, trigger=SolverRun.RESIGNATION_RECOVERY,
        )
        async_result = run_resignation_recovery.delay(teacher.id, term.id, solver_run.id)
        solver_run.celery_task_id = async_result.id
        solver_run.save(update_fields=["celery_task_id"])

        return Response(
            {"id": solver_run.id, "status": solver_run.status}, status=status.HTTP_202_ACCEPTED,
        )


# ---------------------------------------------------------------------------
# Phase 8: Smart Substitution (Proxy) Engine
# ---------------------------------------------------------------------------

class SubstitutionSuggestionsView(ManagedResourceMixin, APIView):
    """
    GET /api/substitution-suggestions/?cell_id=<id>&date=<YYYY-MM-DD>

    Ranked candidate list from core.services.substitution.suggest_substitutes.
    ADMIN/COORDINATOR only (ManagedResourceMixin) -- finding a substitute is
    a management action, same tier as the Phase 6/7 endpoints, unlike the
    read-only TodaysScheduleView below.
    """

    def get(self, request):
        cell_id = request.query_params.get("cell_id")
        date_str = request.query_params.get("date")
        if not cell_id or not date_str:
            return Response(
                {"detail": "cell_id and date query parameters are required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            return Response({"detail": "date must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)

        cell = get_object_or_404(
            self.scope_queryset(TimetableCell.objects.select_related("subject", "teacher", "time_slot")), pk=cell_id
        )

        try:
            candidates = suggest_substitutes(cell, date)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"candidates": candidates})


class SubstitutionCreateView(ManagedResourceMixin, APIView):
    """
    POST /api/substitutions/ {"cell_id", "date", "substitute_teacher_id", "reason"}

    Delegates to core.services.substitution.record_substitution, which
    re-validates the chosen substitute server-side -- never trusts that a
    client-supplied teacher id came from (or is still valid per) a prior
    GET /api/substitution-suggestions/ call.
    """

    def post(self, request):
        data = request.data
        cell_id = data.get("cell_id")
        date_str = data.get("date")
        substitute_teacher_id = data.get("substitute_teacher_id")
        if not cell_id or not date_str or not substitute_teacher_id:
            return Response(
                {"detail": "cell_id, date, and substitute_teacher_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            return Response({"detail": "date must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)

        cell = get_object_or_404(self.scope_queryset(TimetableCell.objects.all()), pk=cell_id)
        substitute_teacher = get_object_or_404(self.scope_queryset(Teacher.objects.all()), pk=substitute_teacher_id)

        try:
            substitution = record_substitution(cell, date, substitute_teacher, reason=data.get("reason", ""))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SubstitutionSerializer(substitution).data, status=status.HTTP_201_CREATED)


class TodaysScheduleView(InstitutionScopedMixin, APIView):
    """
    GET /api/todays-schedule/?date=<YYYY-MM-DD> (defaults to today)

    Deliberately InstitutionScopedMixin, not ManagedResourceMixin: a
    TEACHER-role user can read this. "Who's covering what today" is
    useful to any staff member, not a management action -- same reasoning
    as timetable-grid and solver-runs staying open to every authenticated
    role. Finding/recording a substitute (the two views above) stays
    ADMIN/COORDINATOR only.

    Resolves the date to a day_identifier via AcademicCalendarDay and
    returns every TimetableCell across the whole institution (all class
    divisions) for that day, each annotated with its existing Substitution
    (if any).
    """

    def get(self, request):
        date_str = request.query_params.get("date")
        if date_str:
            try:
                date = datetime.date.fromisoformat(date_str)
            except ValueError:
                return Response(
                    {"detail": "date must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST
                )
        else:
            date = timezone.localdate()

        def not_a_working_day(reason):
            return Response({
                "date": date.isoformat(), "day_identifier": None, "is_working_day": False,
                "reason": reason, "cells": [],
            })

        calendar_day = AcademicCalendarDay.objects.filter(institution=self.institution, date=date).first()
        if calendar_day is None:
            return not_a_working_day(f"No calendar entry exists for {date.isoformat()}.")
        if calendar_day.day_identifier is None:
            return not_a_working_day(
                calendar_day.label or ("Holiday" if calendar_day.is_holiday else "Not a working day")
            )

        active_term = AcademicTerm.objects.filter(institution=self.institution, is_active=True).first()
        if active_term is None:
            return not_a_working_day("No active term is configured for this institution.")

        cells = TimetableCell.objects.filter(
            institution=self.institution, term=active_term, time_slot__day_identifier=calendar_day.day_identifier,
        ).select_related("class_division", "subject", "teacher", "time_slot").order_by(
            "time_slot__period_number", "class_division__name", "class_division__section"
        )

        substitutions_by_cell_id = {
            s.original_cell_id: s
            for s in Substitution.objects.filter(
                date=date, original_cell__in=cells
            ).select_related("substitute_teacher")
        }

        cells_payload = []
        for cell in cells:
            substitution = substitutions_by_cell_id.get(cell.id)
            cells_payload.append({
                "cell_id": cell.id,
                "class_division": f"{cell.class_division.name} - {cell.class_division.section}",
                "subject": cell.subject.name,
                "teacher_id": cell.teacher_id,
                "teacher": cell.teacher.name,
                "time_slot": {
                    "period_number": cell.time_slot.period_number,
                    "start_time": cell.time_slot.start_time,
                    "end_time": cell.time_slot.end_time,
                },
                "substitution": {
                    "substitute_teacher_id": substitution.substitute_teacher_id,
                    "substitute_teacher_name": substitution.substitute_teacher.name,
                    "reason": substitution.reason,
                } if substitution is not None else None,
            })

        return Response({
            "date": date.isoformat(), "day_identifier": calendar_day.day_identifier, "is_working_day": True,
            "cells": cells_payload,
        })
