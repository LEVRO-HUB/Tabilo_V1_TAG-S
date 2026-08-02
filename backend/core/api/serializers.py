from rest_framework import serializers

from core.models import (
    AcademicTerm,
    ClassDivision,
    CourseRequirement,
    Department,
    Institution,
    SolverRun,
    SolverWeightConfig,
    Subject,
    Substitution,
    Teacher,
)


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


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name"]


class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = ["id", "name", "email", "max_periods_per_day", "max_periods_per_week", "is_active"]


class SubjectSerializer(serializers.ModelSerializer):
    """department stays a writable id (the views resolve/validate it
    institution-scoped) with a read-only department_name alongside for
    display, same denormalized-for-a-table approach as
    CourseRequirementSerializer below."""

    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "name", "code", "department", "department_name", "is_elective", "cognitive_load_priority"]


class CourseRequirementSerializer(serializers.ModelSerializer):
    """
    GET/list response shape -- denormalized display fields (subject_name,
    class_division_name, teacher_name) alongside the raw ids, same
    philosophy as TimetableGridView's response, so the frontend table
    doesn't need a second round trip per row.
    """

    term_name = serializers.CharField(source="term.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    class_division_name = serializers.SerializerMethodField()
    teacher_name = serializers.CharField(source="teacher.name", read_only=True, default=None)

    class Meta:
        model = CourseRequirement
        fields = [
            "id", "term", "term_name", "class_division", "class_division_name", "subject", "subject_name",
            "teacher", "teacher_name", "periods_per_week", "is_lab", "block_size", "elective_group",
        ]

    def get_class_division_name(self, obj):
        return f"{obj.class_division.name} - {obj.class_division.section}"


class SubstitutionSerializer(serializers.ModelSerializer):
    """POST /api/substitutions/ response shape."""

    substitute_teacher_name = serializers.CharField(source="substitute_teacher.name", read_only=True)

    class Meta:
        model = Substitution
        fields = [
            "id", "original_cell", "date", "substitute_teacher", "substitute_teacher_name",
            "reason", "created_at",
        ]


class SolverWeightConfigSerializer(serializers.ModelSerializer):
    """
    GET/PATCH /api/solver-weight-config/ response shape. institution is
    intentionally excluded -- the view always resolves the singleton row
    for self.institution, never a client-supplied one.

    min_value/max_value=100 are explicit here because PositiveSmallIntegerField
    only implies a lower bound of 0 by itself -- without these, an
    out-of-range PATCH (e.g. 150) would sail through serializer validation
    and only get caught by the model's solverweightconfig_weights_in_range
    CheckConstraint as a raw IntegrityError. Declaring the upper bound here
    means DRF rejects it with a normal 400 before the DB is ever touched.
    """

    gap_weight = serializers.IntegerField(min_value=0, max_value=100)
    cognitive_load_weight = serializers.IntegerField(min_value=0, max_value=100)
    fair_rotation_weight = serializers.IntegerField(min_value=0, max_value=100)

    class Meta:
        model = SolverWeightConfig
        fields = ["gap_weight", "cognitive_load_weight", "fair_rotation_weight"]


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
