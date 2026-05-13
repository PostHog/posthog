"""Go-to-market strategy generation endpoint.

One GTM entry per team stored in the first FounderProject for that team.

Endpoints:
- POST /api/projects/:id/founder/go-to-market/  — start generation
- GET  /api/projects/:id/founder/go-to-market/  — get current GTM state
"""

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.founder_mode.backend.models import FounderProject
from products.founder_mode.backend.tasks.tasks import run_gtm_task


class GoToMarketRequestSerializer(serializers.Serializer):
    product_description = serializers.CharField(
        min_length=10,
        max_length=5000,
        help_text="Description of the product idea (e.g. 'I want to build a coworking space app')",
    )


class GoToMarketStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["pending", "running", "completed", "failed"])
    result = serializers.JSONField(required=False, allow_null=True)
    error = serializers.CharField(required=False, allow_blank=True)


def _get_or_create_project(team_id: int, name: str) -> FounderProject:
    """Get the team's FounderProject or create one."""
    project = FounderProject.objects.filter(team_id=team_id).first()
    if not project:
        project = FounderProject.objects.create(team_id=team_id, name=name)
    return project


@extend_schema(tags=["founder_mode"])
class GoToMarketViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Generate and retrieve a go-to-market launch plan for the team."""

    scope_object = "INTERNAL"
    serializer_class = GoToMarketRequestSerializer

    @extend_schema(
        request=GoToMarketRequestSerializer,
        responses={202: GoToMarketStatusSerializer},
    )
    def create(self, request: Request, **kwargs) -> Response:
        """
        Start GTM generation.

        POST /api/projects/:id/founder/go-to-market/
        """
        serializer = GoToMarketRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product_description = serializer.validated_data["product_description"]
        project = _get_or_create_project(self.team_id, product_description[:100])

        project.gtm = {"status": "pending", "result": None, "error": ""}
        project.save(update_fields=["gtm", "updated_at"])

        project_id = str(project.id)
        transaction.on_commit(lambda: run_gtm_task.delay(project_id, product_description))

        return Response(project.gtm, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={200: GoToMarketStatusSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        """
        Get current GTM state.

        GET /api/projects/:id/founder/go-to-market/
        """
        project = FounderProject.objects.filter(team_id=self.team_id).first()
        if not project or not project.gtm:
            return Response({"status": None, "result": None, "error": ""}, status=status.HTTP_200_OK)

        return Response(project.gtm, status=status.HTTP_200_OK)
