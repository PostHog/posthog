from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.models.integration import Integration

from products.slack_app.backend.logic.workspace_setup import (
    DefaultProjectError,
    SlackSetupStepKey,
    get_workspace_setup,
    set_default_project,
)


class SlackAppProjectOptionSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the Slack integration that connects this project.")
    project_name = serializers.CharField(help_text="Name of the PostHog project.")
    organization_name = serializers.CharField(help_text="Name of the organization that owns the project.")


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
        child=serializers.ChoiceField(choices=SlackSetupStepKey.choices),
        help_text="Setup steps that apply to this install and are not done yet, in display order. ai_consent: the organization must allow AI data processing. default_project: the Slack workspace connects to 2 or more projects and has no default.",
    )
    project_options = SlackAppProjectOptionSerializer(
        many=True,
        help_text="Projects connected to this Slack workspace that the person can open. Empty unless default_project is a step.",
    )


class SlackAppDefaultProjectSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the Slack integration of the project that becomes the workspace default."
    )


class SlackAppWorkspaceSetupViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "integration"
    scope_object_read_actions = ["retrieve"]
    scope_object_write_actions = ["default_project"]

    def _integration(self, pk: str | None) -> Integration:
        integration = (
            Integration.objects.filter(team_id=self.team_id, kind="slack", id=pk)
            .select_related("team", "team__organization")
            .first()
        )
        if integration is None:
            raise NotFound()
        return integration

    @validated_request(
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Get the web setup steps for a Slack app install",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        setup = get_workspace_setup(self._integration(pk), cast(User, request.user))
        return Response(SlackAppWorkspaceSetupSerializer(setup).data)

    @validated_request(
        request_serializer=SlackAppDefaultProjectSerializer,
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Set the default project for the Slack workspace of a Slack app install",
    )
    @action(detail=True, methods=["post"], url_path="default_project")
    def default_project(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        integration = self._integration(pk)
        user = cast(User, request.user)
        try:
            set_default_project(integration, user, request.validated_data["integration_id"])
        except DefaultProjectError as error:
            raise PermissionDenied(str(error)) from error
        return Response(SlackAppWorkspaceSetupSerializer(get_workspace_setup(integration, user)).data)
