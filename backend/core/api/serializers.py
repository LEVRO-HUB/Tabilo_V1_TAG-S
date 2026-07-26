from rest_framework import serializers

from core.models import AcademicTerm, ClassDivision, Institution


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
