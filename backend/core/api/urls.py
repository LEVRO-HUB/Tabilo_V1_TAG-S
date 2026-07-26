from django.urls import path

from core.api.views import (
    ClassDivisionListView,
    LoginView,
    SolverRunDetailView,
    SolverRunTriggerView,
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
]
