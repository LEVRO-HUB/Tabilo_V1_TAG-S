from rest_framework import serializers

from core.models import AcademicTerm, ClassDivision, Institution, SolverRun


class InstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = ["id", "name", "institution_type", "cycle_length"]


class AcademicTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicTerm
        fields = ["id", "name", "start_date", "end_date", "is_active"]


class ClassDivisionSerializer(serializers.ModelSerializer):
    department = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = ClassDivision
        fields = ["id", "name", "section", "department"]


class SolverRunSerializer(serializers.ModelSerializer):
    """
    GET /api/solver-runs/<id>/ response shape -- the frontend polls this.
    status is one of SolverRun.STATUS_CHOICES (PENDING/RUNNING/SUCCESS/
    FAILED); SUCCESS and FAILED are the only terminal values.
    """

    class Meta:
        model = SolverRun
        fields = [
            "id", "status", "trigger", "objective_value", "error_message",
            "created_at", "started_at", "finished_at",
        ]
