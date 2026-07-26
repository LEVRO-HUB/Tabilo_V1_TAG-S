"""
Tabilo — institution-scoping for the REST API (Phase 5b)

Every institution-scoped endpoint should mix in InstitutionScopedMixin
(alongside APIView, generics.ListAPIView, or any other DRF view base). This
is the single place that encodes three rules every future endpoint must
follow -- read this before adding a new view:

1. A request from an authenticated user with no UserProfile is rejected
   with 403 (via HasInstitutionProfile, wired into permission_classes
   here) before any view logic runs -- there is no institution to scope to.

2. `self.institution` gives the requester's institution, read once from
   request.user.profile.institution. Views should never touch
   request.user.profile directly.

3. Any queryset a view exposes MUST be passed through self.scope_queryset()
   so that requesting an object belonging to a DIFFERENT institution
   resolves to 404, not 403 -- don't leak whether the object exists at all.
   DRF's generic get_object() already turns "not in this queryset" into a
   404 for you; for hand-written lookups (e.g. from query params rather
   than a URL pk), use scope_queryset() + get_object_or_404() yourself, the
   same way core/api/views.py's TimetableGridView does. Never write a
   separate "wrong institution -> 403" branch anywhere -- that's exactly
   the leak this rule exists to prevent.
"""

from rest_framework import permissions


class HasInstitutionProfile(permissions.BasePermission):
    """Rejects (403) any authenticated request from a user with no
    UserProfile -- there is no institution to scope the request to."""

    message = "Your account has no institution profile; contact an administrator."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile")


class InstitutionScopedMixin:
    """Mix into any DRF view that should only ever see one institution's
    data. Requires authentication (IsAuthenticated) and a UserProfile
    (HasInstitutionProfile) -- see module docstring for the three rules
    this enforces."""

    permission_classes = [permissions.IsAuthenticated, HasInstitutionProfile]

    @property
    def institution(self):
        return self.request.user.profile.institution

    def scope_queryset(self, queryset):
        """Filter a queryset to the requester's institution only."""
        return queryset.filter(institution=self.institution)
