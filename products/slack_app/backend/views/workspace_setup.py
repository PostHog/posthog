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
    MAX_CHANNELS_TO_JOIN,
    SlackSetupEntry,
    SlackSetupStepKey,
    WorkspaceSettingsError,
    get_workspace_setup,
    join_channels as join_slack_channels,
    list_channel_options,
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
        help_text=(
            "Setup steps that apply to this install and are not done yet, in display order. "
            "ai_consent: the organization must allow AI data processing. "
            "default_project: the Slack workspace connects to 2 or more projects and has no default. "
            "channels: the install can join channels, and the setup started on the Slack page."
        ),
    )
    project_options = SlackAppProjectOptionSerializer(
        many=True,
        help_text="Projects connected to this Slack workspace that the person can open. Empty unless default_project is a step.",
    )


class SlackAppWorkspaceSetupQuerySerializer(serializers.Serializer):
    entry = serializers.ChoiceField(
        choices=SlackSetupEntry.choices,
        default=SlackSetupEntry.OTHER,
        help_text="Where the Slack install started. slack_page adds the steps for a person who sets up Slack on purpose.",
    )


class SlackAppDefaultProjectSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the Slack integration of the project that becomes the workspace default."
    )


class SlackAppChannelOptionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Slack channel ID.")
    name = serializers.CharField(help_text="Channel name, without the leading #.")
    is_member = serializers.BooleanField(help_text="Whether PostHog is already in the channel.")


class SlackAppChannelOptionsSerializer(serializers.Serializer):
    channels = SlackAppChannelOptionSerializer(
        many=True, help_text="Public channels that PostHog can join. Shared channels are left out."
    )


class SlackAppJoinChannelsSerializer(serializers.Serializer):
    channel_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=MAX_CHANNELS_TO_JOIN,
        help_text="IDs of the public channels that PostHog joins.",
    )
    post_welcome = serializers.BooleanField(
        default=False,
        help_text="Whether PostHog posts its welcome message in each channel it joins. When false, it joins quietly.",
    )


class SlackAppChannelJoinResultSerializer(serializers.Serializer):
    channel_id = serializers.CharField(help_text="Slack channel ID.")
    error = serializers.CharField(
        allow_null=True, help_text="Slack's error code when PostHog could not join, or null when it joined."
    )


class SlackAppJoinChannelsResultSerializer(serializers.Serializer):
    results = SlackAppChannelJoinResultSerializer(many=True, help_text="The result for each channel, in request order.")


class SlackAppWorkspaceSetupViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "integration"
    scope_object_read_actions = ["retrieve", "channels"]
    scope_object_write_actions = ["default_project", "join_channels"]

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
        query_serializer=SlackAppWorkspaceSetupQuerySerializer,
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Get the web setup steps for a Slack app install",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        entry = SlackSetupEntry(request.validated_query_data["entry"])
        setup = get_workspace_setup(self._integration(pk), cast(User, request.user), entry)
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
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        setup = get_workspace_setup(integration, user, SlackSetupEntry.OTHER)
        return Response(SlackAppWorkspaceSetupSerializer(setup).data)

    @validated_request(
        responses={200: OpenApiResponse(response=SlackAppChannelOptionsSerializer)},
        summary="List the public channels that PostHog can join for a Slack app install",
    )
    @action(detail=True, methods=["get"], url_path="channels")
    def channels(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        options = list_channel_options(self._integration(pk))
        return Response(SlackAppChannelOptionsSerializer({"channels": options}).data)

    @validated_request(
        request_serializer=SlackAppJoinChannelsSerializer,
        responses={200: OpenApiResponse(response=SlackAppJoinChannelsResultSerializer)},
        summary="Add PostHog to public channels of a Slack app install",
    )
    @action(detail=True, methods=["post"], url_path="join_channels")
    def join_channels(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            results = join_slack_channels(
                self._integration(pk),
                cast(User, request.user),
                request.validated_data["channel_ids"],
                post_welcome=request.validated_data["post_welcome"],
            )
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        return Response(SlackAppJoinChannelsResultSerializer({"results": results}).data)
