"""
Tabilo — REST API views (Phase 5b)

A scoped API: authentication + institution-scoped access, plus one
purpose-built endpoint (TimetableGridView) for the first frontend screen.
Not a full CRUD API yet -- see core/api/permissions.py for the
institution-scoping rules every endpoint here follows.
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.permissions import InstitutionScopedMixin
from core.api.serializers import AcademicTermSerializer, ClassDivisionSerializer, InstitutionSerializer
from core.models import AcademicTerm, ClassDivision, TimeSlot, TimetableCell


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
