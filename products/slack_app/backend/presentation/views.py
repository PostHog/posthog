from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.models import User
from posthog.models.user_integration import ReauthorizationRequired

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.slack_app.backend.facade.api import (
    get_slack_app_settings,
    get_slack_workspace_setup,
    join_slack_setup_channels,
    list_slack_channel_settings,
    list_slack_repository_options,
    list_slack_setup_channels,
    set_slack_workspace_default_project,
    update_slack_channel_settings,
    update_slack_personal_settings,
    update_slack_workspace_settings,
)
from products.slack_app.backend.facade.enums import (
    SlackChannelQuestionMode,
    SlackReactionKind,
    SlackSetupEntry,
    SlackSetupStepKey,
    SlackThreadJoinMode,
    SlackUntaggedMode,
)
from products.slack_app.backend.facade.types import (
    MAX_CHANNELS_TO_JOIN,
    ChannelCatalogBusy,
    SlackPersonalSettingsChange,
    SlackReactionChoice,
    SlackSettingsInvalid,
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


GITHUB_RECONNECT = "Your GitHub connection has expired. Reconnect GitHub in your personal settings."
GITHUB_RATE_LIMITED = "GitHub is limiting requests for your account. Try again in a few minutes."
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


class SlackAppReactionChoiceSerializer(serializers.Serializer):
    emoji = serializers.CharField(
        allow_null=True,
        required=False,
        max_length=102,
        help_text="Slack emoji name, such as eyes or a custom emoji of the workspace. Colons are allowed. Null inherits.",
    )
    enabled = serializers.BooleanField(
        allow_null=True, required=False, help_text="Whether PostHog adds this reaction. Null inherits."
    )


class SlackAppReactionChoicesSerializer(serializers.Serializer):
    working = SlackAppReactionChoiceSerializer(
        required=False, help_text="Added to a message when PostHog starts on the request."
    )
    done = SlackAppReactionChoiceSerializer(
        required=False, help_text="Added when PostHog replies. The working reaction is removed."
    )
    error = SlackAppReactionChoiceSerializer(required=False, help_text="Added when the request fails.")
    polite = SlackAppReactionChoiceSerializer(
        required=False, help_text="Added after PostHog replies to a message that says please or thanks."
    )


class SlackAppResolvedReactionSerializer(serializers.Serializer):
    emoji = serializers.CharField(help_text="Slack emoji name that PostHog uses.")
    enabled = serializers.BooleanField(help_text="Whether PostHog adds this reaction.")


class SlackAppResolvedReactionsSerializer(serializers.Serializer):
    working = SlackAppResolvedReactionSerializer(help_text="The reaction when PostHog starts on a request.")
    done = SlackAppResolvedReactionSerializer(help_text="The reaction when PostHog replies.")
    error = SlackAppResolvedReactionSerializer(help_text="The reaction when the request fails.")
    polite = SlackAppResolvedReactionSerializer(help_text="The reaction to a message that says please or thanks.")


class SlackAppWorkspaceSettingsSerializer(serializers.Serializer):
    reactions = SlackAppReactionChoicesSerializer(
        help_text="The workspace's reaction choices. Null fields use PostHog's defaults."
    )
    external_channels_enabled = serializers.BooleanField(
        help_text="Whether PostHog works in Slack channels shared with other organizations."
    )


class SlackAppPersonalSettingsSerializer(serializers.Serializer):
    slack_user_id = serializers.CharField(
        allow_null=True,
        help_text="The Slack user this person linked in this workspace. Null when they have not linked one.",
    )
    reactions = SlackAppReactionChoicesSerializer(
        help_text="This person's reaction choices. Null fields use the workspace choice."
    )
    effective_reactions = SlackAppResolvedReactionsSerializer(
        help_text="The reactions PostHog adds to this person's messages, after the workspace and default fallbacks."
    )
    default_integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the Slack integration of this person's own default project. Null uses the workspace default.",
    )
    project_options = SlackAppProjectOptionSerializer(
        many=True, help_text="Projects connected to this Slack workspace that this person can open."
    )
    untagged_followup_mode = serializers.ChoiceField(
        choices=SlackUntaggedMode.choices,
        help_text="What PostHog does with untagged replies in threads this person started.",
    )
    untagged_question_mode = serializers.ChoiceField(
        choices=SlackUntaggedMode.choices,
        help_text="What PostHog does with this person's top-level channel questions that do not tag it.",
    )
    thread_join_mode = serializers.ChoiceField(
        choices=SlackThreadJoinMode.choices,
        help_text="What PostHog does when someone else tags it in a thread this person started.",
    )
    auto_model_choice = serializers.BooleanField(
        help_text="Whether PostHog picks the model for each task this person starts from Slack."
    )
    feature_tips_enabled = serializers.BooleanField(
        help_text="Whether PostHog sends this person short tips about Slack app features."
    )
    chatgpt_apps_enabled = serializers.BooleanField(
        allow_null=True,
        help_text="Whether Slack tasks on this person's ChatGPT plan can use the apps connected to that plan. Null when this person has no ChatGPT plan that Slack tasks can use.",
    )


class SlackAppSettingsSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="ID of the Slack integration that these settings are for.")
    slack_workspace_name = serializers.CharField(
        allow_null=True, help_text="Name of the Slack workspace, as Slack sent it at install time."
    )
    can_edit_workspace = serializers.BooleanField(
        help_text="Whether this person can change workspace settings: the person who installed Slack, or a project admin."
    )
    workspace = SlackAppWorkspaceSettingsSerializer(help_text="Settings for everyone in the Slack workspace.")
    personal = SlackAppPersonalSettingsSerializer(help_text="Settings for this person's own Slack messages.")


class SlackAppWorkspaceSettingsUpdateSerializer(serializers.Serializer):
    reactions = SlackAppReactionChoicesSerializer(
        required=False,
        help_text="Replaces the workspace's reaction choices. A reaction left out inherits PostHog's default.",
    )
    external_channels_enabled = serializers.BooleanField(
        required=False, help_text="Whether PostHog works in Slack channels shared with other organizations."
    )


class SlackAppPersonalSettingsUpdateSerializer(serializers.Serializer):
    reactions = SlackAppReactionChoicesSerializer(
        required=False,
        help_text="Replaces this person's reaction choices. A reaction left out inherits the workspace choice.",
    )
    default_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the Slack integration of the project this person's mentions route to. Null uses the workspace default.",
    )
    untagged_followup_mode = serializers.ChoiceField(
        choices=SlackUntaggedMode.choices,
        required=False,
        help_text="What PostHog does with untagged replies in threads this person started.",
    )
    untagged_question_mode = serializers.ChoiceField(
        choices=SlackUntaggedMode.choices,
        required=False,
        help_text="What PostHog does with this person's top-level channel questions that do not tag it.",
    )
    thread_join_mode = serializers.ChoiceField(
        choices=SlackThreadJoinMode.choices,
        required=False,
        help_text="What PostHog does when someone else tags it in a thread this person started.",
    )
    auto_model_choice = serializers.BooleanField(
        required=False, help_text="Whether PostHog picks the model for each task this person starts from Slack."
    )
    feature_tips_enabled = serializers.BooleanField(
        required=False, help_text="Whether PostHog sends this person short tips about Slack app features."
    )
    chatgpt_apps_enabled = serializers.BooleanField(
        required=False,
        help_text="Whether Slack tasks on this person's ChatGPT plan can use the apps connected to that plan. Applies to tasks started after the change.",
    )


class SlackAppChannelSettingsSerializer(serializers.Serializer):
    slack_channel_id = serializers.CharField(help_text="Slack channel ID.")
    default_integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the Slack integration of the project that mentions in this channel route to. Null inherits.",
    )
    default_repository = serializers.CharField(
        allow_null=True, help_text="Repository, as owner/name, that tasks started in this channel use. Null inherits."
    )
    untagged_question_mode = serializers.ChoiceField(
        choices=SlackChannelQuestionMode.choices,
        allow_null=True,
        help_text="What PostHog does with top-level questions in this channel that do not tag it. Null uses each person's mode. A channel only makes it stricter.",
    )
    updated_by_name = serializers.CharField(
        allow_null=True,
        help_text="First name of the person who last changed this channel's settings. Null when unknown.",
    )
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When this channel's settings last changed.")


class SlackAppRepositoryOptionsSerializer(serializers.Serializer):
    repositories = serializers.ListField(
        child=serializers.CharField(),
        help_text="Repositories as owner/name from this person's own GitHub installs, sorted by name.",
    )
    github_connected = serializers.BooleanField(
        help_text="Whether this person connected a personal GitHub account. False means repositories is empty."
    )


class SlackAppChannelSettingsListSerializer(serializers.Serializer):
    channels = SlackAppChannelSettingsSerializer(
        many=True, help_text="Channels that this install's organization gave at least one setting."
    )


class SlackAppChannelSettingsUpdateSerializer(serializers.Serializer):
    default_integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="ID of the Slack integration of a project connected to this workspace. Null inherits.",
    )
    default_repository = serializers.CharField(
        allow_null=True, max_length=255, help_text="Repository as owner/name. Null inherits."
    )
    untagged_question_mode = serializers.ChoiceField(
        choices=SlackChannelQuestionMode.choices,
        allow_null=True,
        help_text="What PostHog does with top-level questions in this channel that do not tag it. Null uses each person's mode. A channel only makes it stricter.",
    )


def _reactions(data: dict[str, dict[str, Any]]) -> dict[SlackReactionKind, SlackReactionChoice]:
    return {
        SlackReactionKind(kind): SlackReactionChoice(emoji=choice.get("emoji"), enabled=choice.get("enabled"))
        for kind, choice in data.items()
    }


def _personal_change(data: dict[str, Any]) -> SlackPersonalSettingsChange:
    fields: dict[str, Any] = {key: data[key] for key in PERSONAL_SETTING_FIELDS if key in data}
    if "reactions" in data:
        fields["reactions"] = _reactions(data["reactions"])
    return SlackPersonalSettingsChange(**fields)


PERSONAL_SETTING_FIELDS = (
    "default_integration_id",
    "untagged_followup_mode",
    "untagged_question_mode",
    "thread_join_mode",
    "auto_model_choice",
    "feature_tips_enabled",
    "chatgpt_apps_enabled",
)


class SlackAppSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "integration"
    scope_object_read_actions = ["retrieve", "channels", "repositories"]
    scope_object_write_actions = ["workspace", "personal", "update_channel"]

    def read_object(self) -> IntegrationRecord | None:
        try:
            return IntegrationManager.slack.oauth.get(self.team_id, int(self.kwargs.get("pk") or ""))
        except (IntegrationNotFound, ValueError):
            return None

    def object_access_ref(self, record: IntegrationRecord) -> ObjectAccessRef:
        return ObjectAccessRef(
            resource="integration", id=str(record.id), team_id=record.team_id, created_by_id=record.created_by_id
        )

    def _integration_id(self, pk: str | None) -> int:
        # get_object() runs the access-control check on this install, so a member restricted on it gets a 403.
        return self.get_object().id

    @validated_request(
        responses={200: OpenApiResponse(response=SlackAppSettingsSerializer)},
        summary="Get the personal and workspace settings of a Slack app install",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            settings = get_slack_app_settings(self.team_id, self._integration_id(pk), cast(User, request.user))
        except SlackSetupNotFound as error:
            raise NotFound() from error
        return Response(SlackAppSettingsSerializer(settings).data)

    @validated_request(
        request_serializer=SlackAppWorkspaceSettingsUpdateSerializer,
        responses={200: OpenApiResponse(response=SlackAppSettingsSerializer)},
        summary="Change the workspace settings of a Slack app install",
    )
    @action(detail=True, methods=["patch"], url_path="workspace")
    def workspace(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        data = request.validated_data
        try:
            settings = update_slack_workspace_settings(
                self.team_id,
                self._integration_id(pk),
                cast(User, request.user),
                reactions=_reactions(data["reactions"]) if "reactions" in data else None,
                external_channels_enabled=data.get("external_channels_enabled"),
            )
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        except SlackSettingsInvalid as error:
            raise ValidationError(str(error)) from error
        return Response(SlackAppSettingsSerializer(settings).data)

    @validated_request(
        request_serializer=SlackAppPersonalSettingsUpdateSerializer,
        responses={200: OpenApiResponse(response=SlackAppSettingsSerializer)},
        summary="Change your own settings for a Slack app install",
    )
    @action(detail=True, methods=["patch"], url_path="personal")
    def personal(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            settings = update_slack_personal_settings(
                self.team_id,
                self._integration_id(pk),
                cast(User, request.user),
                _personal_change(request.validated_data),
            )
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except WorkspaceSettingsError as error:
            raise PermissionDenied(str(error)) from error
        except SlackSettingsInvalid as error:
            raise ValidationError(str(error)) from error
        return Response(SlackAppSettingsSerializer(settings).data)

    @validated_request(
        responses={
            200: OpenApiResponse(response=SlackAppRepositoryOptionsSerializer),
            403: OpenApiResponse(description=GITHUB_RECONNECT),
            429: OpenApiResponse(description=GITHUB_RATE_LIMITED),
        },
        summary="List the repositories this person can set as a channel's default repository",
    )
    # user:read as well, because the list comes from the person's own GitHub installs, not from the project.
    @action(detail=True, methods=["get"], url_path="repositories", required_scopes=["integration:read", "user:read"])
    def repositories(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            options = list_slack_repository_options(self.team_id, self._integration_id(pk), cast(User, request.user))
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except ReauthorizationRequired as error:
            raise PermissionDenied(GITHUB_RECONNECT) from error
        except GitHubRateLimitError as error:
            raise Throttled(detail=GITHUB_RATE_LIMITED) from error
        return Response(SlackAppRepositoryOptionsSerializer(options).data)

    @validated_request(
        responses={200: OpenApiResponse(response=SlackAppChannelSettingsListSerializer)},
        summary="List the channel settings of a Slack app install",
    )
    @action(detail=True, methods=["get"], url_path="channels")
    def channels(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        try:
            channels = list_slack_channel_settings(self.team_id, self._integration_id(pk))
        except SlackSetupNotFound as error:
            raise NotFound() from error
        return Response(SlackAppChannelSettingsListSerializer({"channels": channels}).data)

    @validated_request(
        request_serializer=SlackAppChannelSettingsUpdateSerializer,
        responses={200: OpenApiResponse(response=SlackAppChannelSettingsSerializer)},
        summary="Replace the settings of one channel of a Slack app install",
    )
    @action(detail=True, methods=["put"], url_path=r"channels/(?P<slack_channel_id>[^/.]+)")
    def update_channel(
        self, request: Request, pk: str | None = None, slack_channel_id: str = "", **kwargs: Any
    ) -> Response:
        data = request.validated_data
        mode = data["untagged_question_mode"]
        try:
            channel = update_slack_channel_settings(
                self.team_id,
                self._integration_id(pk),
                cast(User, request.user),
                slack_channel_id=slack_channel_id,
                default_integration_id=data["default_integration_id"],
                default_repository=data["default_repository"],
                untagged_question_mode=SlackChannelQuestionMode(mode) if mode else None,
            )
        except SlackSetupNotFound as error:
            raise NotFound() from error
        except SlackSettingsInvalid as error:
            raise ValidationError(str(error)) from error
        return Response(SlackAppChannelSettingsSerializer(channel).data)
