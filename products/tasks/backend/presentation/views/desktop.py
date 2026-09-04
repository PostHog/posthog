from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.desktop_serializers import DesktopBetaTermsAcceptanceSerializer


class DesktopBetaTermsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "organization"
    permission_classes = [OrganizationAdminWritePermissions]
    pagination_class = None

    @extend_schema(responses={200: DesktopBetaTermsAcceptanceSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        acceptance = tasks_facade.get_desktop_beta_terms_acceptance(self.organization.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)

    @extend_schema(request=None, responses={200: DesktopBetaTermsAcceptanceSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        acceptance = tasks_facade.accept_desktop_beta_terms(self.organization.id, user.id)
        self._record_desktop_product_intent(user)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)

    def _record_desktop_product_intent(self, user: User) -> None:
        """Record product intent for PostHog Desktop, so growth's product push stops advertising it
        and closes an active Desktop campaign as adopted. Acceptance is org-wide; attribute the
        intent to any team in the org (the growth surface check is org-scoped). Best-effort."""
        from posthog.models.product_intent.product_intent import (
            ProductIntent,  # noqa: PLC0415 — off the model import path
        )
        from posthog.schema_enums import ProductIntentContext, ProductKey  # noqa: PLC0415

        team = self.organization.teams.first()
        if team is None:
            return
        try:
            ProductIntent.register(
                team=team,
                product_type=ProductKey.POSTHOG_DESKTOP,
                context=ProductIntentContext.DESKTOP_BETA_TERMS_ACCEPTED,
                user=user,
            )
        except Exception:
            import structlog  # noqa: PLC0415

            structlog.get_logger(__name__).warning("desktop_beta_product_intent_failed", exc_info=True)
