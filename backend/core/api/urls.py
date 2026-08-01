from django.urls import path

from core.api.views import (
    ClassDivisionListView,
    CourseRequirementDetailView,
    CourseRequirementListCreateView,
    DepartmentListView,
    LoginView,
    ResignationRecoveryTriggerView,
    SolverRunDetailView,
    SolverRunTriggerView,
    SubjectDetailView,
    SubjectListCreateView,
    TeacherDetailView,
    TeacherListCreateView,
    TermListView,
    TimetableGridView,
)

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="api-login"),
    path("terms/", TermListView.as_view(), name="api-terms"),
    path("class-divisions/", ClassDivisionListView.as_view(), name="api-class-divisions"),
    path("timetable-grid/", TimetableGridView.as_view(), name="api-timetable-grid"),
    path("solver-runs/", SolverRunTriggerView.as_view(), name="api-solver-run-trigger"),
    path("solver-runs/<int:pk>/", SolverRunDetailView.as_view(), name="api-solver-run-detail"),
    path(
        "resignation-recovery/",
        ResignationRecoveryTriggerView.as_view(),
        name="api-resignation-recovery-trigger",
    ),
    path("departments/", DepartmentListView.as_view(), name="api-departments"),
    path("teachers/", TeacherListCreateView.as_view(), name="api-teachers"),
    path("teachers/<int:pk>/", TeacherDetailView.as_view(), name="api-teacher-detail"),
    path("subjects/", SubjectListCreateView.as_view(), name="api-subjects"),
    path("subjects/<int:pk>/", SubjectDetailView.as_view(), name="api-subject-detail"),
    path("course-requirements/", CourseRequirementListCreateView.as_view(), name="api-course-requirements"),
    path(
        "course-requirements/<int:pk>/",
        CourseRequirementDetailView.as_view(),
        name="api-course-requirement-detail",
    ),
]
