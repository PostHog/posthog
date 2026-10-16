from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.integration import Integration

from products.slack_app.backend.logic.workspace_setup import get_workspace_setup


class SlackAppWorkspaceSetupSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the Slack integration that this setup is for.")
    slack_workspace_name = serializers.CharField(
        allow_null=True, help_text="Name of the Slack workspace, as Slack sent it at install time."
    )
    open_slack_url = serializers.URLField(
        allow_null=True,
        help_text="Link that opens the PostHog app's direct message in this Slack workspace. Null when the install has no app ID.",
    )
    steps = serializers.ListField(
        child=serializers.CharField(),
        help_text="Keys of the setup steps that apply to this install and are not done yet, in display order.",
    )


class SlackAppWorkspaceSetupViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "integration"

    @extend_schema(
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Get the workspace setup steps for a Slack app install",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        integration = Integration.objects.filter(team_id=self.team_id, kind="slack", id=pk).first()
        if integration is None:
            raise NotFound()
        setup = get_workspace_setup(integration, cast(User, request.user))
        return Response(SlackAppWorkspaceSetupSerializer(setup).data)
