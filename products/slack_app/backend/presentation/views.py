from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.slack_app.backend.facade.api import (
    get_slack_workspace_setup,
    join_slack_setup_channels,
    list_slack_setup_channels,
    set_slack_workspace_default_project,
)
from products.slack_app.backend.facade.enums import SlackSetupEntry, SlackSetupStepKey
from products.slack_app.backend.facade.types import (
    MAX_CHANNELS_TO_JOIN,
    ChannelCatalogBusy,
    SlackSetupNotFound,
    WorkspaceSettingsError,
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
    can_post_channel_welcome = serializers.BooleanField(
        help_text=(
            "Whether a channel join from this setup can post the welcome message in the channel. "
            "False when channels is not a step, or when the workspace sends the welcome only to the inviter or turns it off."
        ),
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
        default=True,
        help_text="Whether PostHog posts its welcome message in each channel it joins. When false, it joins quietly.",
    )


class SlackAppChannelJoinResultSerializer(serializers.Serializer):
    channel_id = serializers.CharField(help_text="Slack channel ID.")
    error = serializers.CharField(
        allow_null=True, help_text="Slack's error code when PostHog could not join, or null when it joined."
    )


class SlackAppJoinChannelsResultSerializer(serializers.Serializer):
    results = SlackAppChannelJoinResultSerializer(many=True, help_text="The result for each channel, in request order.")


CHANNEL_LIST_THROTTLED = (
    "Slack's channel list for this workspace is loading in another request, or it was loaded too often recently."
)


class SlackAppWorkspaceSetupViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "integration"
    scope_object_read_actions = ["retrieve", "channels"]
    scope_object_write_actions = ["default_project", "join_channels"]

    def _integration_id(self, pk: str | None) -> int:
        try:
            return int(pk or "")
        except ValueError:
            raise NotFound()

    @validated_request(
        query_serializer=SlackAppWorkspaceSetupQuerySerializer,
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Get the web setup steps for a Slack app install",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        entry = SlackSetupEntry(request.validated_query_data["entry"])
        try:
            setup = get_slack_workspace_setup(self.team_id, self._integration_id(pk), cast(User, request.user), entry)
        except SlackSetupNotFound as error:
            raise NotFound() from error
        return Response(SlackAppWorkspaceSetupSerializer(setup).data)

    @validated_request(
        request_serializer=SlackAppDefaultProjectSerializer,
        responses={200: OpenApiResponse(response=SlackAppWorkspaceSetupSerializer)},
        summary="Set the default project for the Slack workspace of a Slack app install",
    )
    @action(detail=True, methods=["post"], url_path="default_project")
    def default_project(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            setup = set_slack_workspace_default_project(
                self.team_id,
                self._integration_id(pk),
                cast(User, request.user),
                request.validated_data["integration_id"],
            )
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        return Response(SlackAppWorkspaceSetupSerializer(setup).data)

    @validated_request(
        responses={
            200: OpenApiResponse(response=SlackAppChannelOptionsSerializer),
            429: OpenApiResponse(description=CHANNEL_LIST_THROTTLED),
        },
        summary="List the public channels that PostHog can join for a Slack app install",
    )
    @action(detail=True, methods=["get"], url_path="channels")
    def channels(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            options = list_slack_setup_channels(self.team_id, self._integration_id(pk))
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except ChannelCatalogBusy as error:
            raise Throttled(detail=str(error)) from error
        return Response(SlackAppChannelOptionsSerializer({"channels": options}).data)

    @validated_request(
        request_serializer=SlackAppJoinChannelsSerializer,
        responses={
            200: OpenApiResponse(response=SlackAppJoinChannelsResultSerializer),
            429: OpenApiResponse(description=CHANNEL_LIST_THROTTLED),
        },
        summary="Add PostHog to public channels of a Slack app install",
    )
    @action(detail=True, methods=["post"], url_path="join_channels")
    def join_channels(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            results = join_slack_setup_channels(
                self.team_id,
                self._integration_id(pk),
                cast(User, request.user),
                request.validated_data["channel_ids"],
                post_welcome=request.validated_data["post_welcome"],
            )
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        except ChannelCatalogBusy as error:
            raise Throttled(detail=str(error)) from error
        return Response(SlackAppJoinChannelsResultSerializer({"results": results}).data)
