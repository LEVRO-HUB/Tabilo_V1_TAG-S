from django.contrib import admin

from core.models import (
    Institution,
    Department,
    AcademicTerm,
    Teacher,
    Subject,
    TeacherSubjectEligibility,
    ClassDivision,
    TimeGridConfig,
    AcademicCalendarDay,
    TimeSlot,
    ElectiveGroup,
    CourseRequirement,
    FacultyDutyBlock,
    TimetableCell,
    SolverRun,
    SolverWeightConfig,
)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("name", "institution_type", "cycle_length")
    list_filter = ("institution_type",)
    search_fields = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "institution")
    list_filter = ("institution",)
    search_fields = ("name",)


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "start_date", "end_date", "is_active")
    list_filter = ("institution", "is_active")


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "max_periods_per_day", "max_periods_per_week", "is_active")
    list_filter = ("institution", "is_active")
    search_fields = ("name", "email")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "institution", "is_elective", "cognitive_load_priority")
    list_filter = ("institution", "department", "is_elective", "cognitive_load_priority")
    search_fields = ("name", "code")


@admin.register(TeacherSubjectEligibility)
class TeacherSubjectEligibilityAdmin(admin.ModelAdmin):
    list_display = ("teacher", "subject", "institution")
    list_filter = ("institution",)


@admin.register(ClassDivision)
class ClassDivisionAdmin(admin.ModelAdmin):
    list_display = ("name", "section", "department", "institution")
    list_filter = ("institution", "department")


@admin.register(TimeGridConfig)
class TimeGridConfigAdmin(admin.ModelAdmin):
    list_display = ("institution", "periods_per_day", "period_duration_minutes", "day_start_time")


@admin.register(AcademicCalendarDay)
class AcademicCalendarDayAdmin(admin.ModelAdmin):
    list_display = ("date", "day_identifier", "is_holiday", "label", "institution")
    list_filter = ("institution", "is_holiday")


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("institution", "day_identifier", "period_number", "start_time", "end_time", "is_break")
    list_filter = ("institution", "day_identifier", "is_break")


@admin.register(ElectiveGroup)
class ElectiveGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "term", "institution")
    list_filter = ("institution", "term")


@admin.register(CourseRequirement)
class CourseRequirementAdmin(admin.ModelAdmin):
    list_display = ("class_division", "subject", "teacher", "periods_per_week", "is_lab", "block_size", "term")
    list_filter = ("institution", "term", "is_lab")


@admin.register(FacultyDutyBlock)
class FacultyDutyBlockAdmin(admin.ModelAdmin):
    list_display = ("teacher", "duty_type", "time_slot", "term")
    list_filter = ("institution", "term", "duty_type")


@admin.register(TimetableCell)
class TimetableCellAdmin(admin.ModelAdmin):
    list_display = ("class_division", "time_slot", "subject", "teacher", "term", "elective_group", "is_locked")
    list_filter = ("institution", "term", "is_locked")


@admin.register(SolverRun)
class SolverRunAdmin(admin.ModelAdmin):
    list_display = ("status", "institution", "term", "objective_value", "created_at")
    list_filter = ("institution", "term", "status")


@admin.register(SolverWeightConfig)
class SolverWeightConfigAdmin(admin.ModelAdmin):
    list_display = ("institution", "gap_weight", "cognitive_load_weight", "fair_rotation_weight")
