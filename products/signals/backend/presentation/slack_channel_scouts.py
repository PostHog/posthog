from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.permissions import APIScopePermission

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.facade import api as signals_facade
from products.signals.backend.facade.slack_channel_scouts import (
    MAX_SLACK_SCOUT_CHANNELS,
    SLACK_SCOUT_NAME_MAX_LENGTH,
    SLACK_SCOUT_SOURCE_PRODUCT,
    SlackChannelSelectionError,
    list_slack_channel_sources,
    plan_slack_channel_scout,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission

SLACK_SCOUT_STEER_MAX_LENGTH = 4000


class SlackScoutChannelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The Slack channel id, which is also the name of its warehouse schema.")
    name = serializers.CharField(help_text="The channel name, without the leading #.")
    table_name = serializers.CharField(
        allow_null=True,
        help_text="HogQL name of the channel's message table. Null until the channel's first sync writes the table.",
    )


class SlackScoutChannelSourceSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Id of the Slack data warehouse source.")
    channels = SlackScoutChannelSerializer(many=True, help_text="Channels the source syncs, ordered by name.")


class SlackScoutChannelSourcesSerializer(serializers.Serializer):
    sources = SlackScoutChannelSourceSerializer(
        many=True,
        help_text="The project's Slack data warehouse sources. Empty when the project has not connected Slack.",
    )


class SlackChannelScoutCreateSerializer(serializers.Serializer):
    display_name = serializers.CharField(
        max_length=SLACK_SCOUT_NAME_MAX_LENGTH,
        help_text="Name shown wherever people identify this scout. The scout's skill name is generated from it.",
    )
    source_id = serializers.UUIDField(help_text="Id of the Slack data warehouse source to read.")
    channel_ids = serializers.ListField(
        child=serializers.CharField(max_length=64),
        min_length=1,
        max_length=MAX_SLACK_SCOUT_CHANNELS,
        help_text=(
            f"Ids of the channels to read, at most {MAX_SLACK_SCOUT_CHANNELS}. Every channel must already have "
            "synced its message table."
        ),
    )
    steer = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=SLACK_SCOUT_STEER_MAX_LENGTH,
        help_text=(
            "What the scout looks for in the messages, in plain words. Blank uses a default focus on bug reports, "
            "repeated requests, and complaints."
        ),
    )
    run_cron_schedule = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=100,
        help_text=(
            "Optional five-field cron expression evaluated in the project timezone, e.g. '0 9 * * 1-5'. "
            "Occurrences must be at least 30 minutes apart. Omit for the daily default."
        ),
    )
    emit = serializers.BooleanField(
        default=True,
        help_text="Whether the scout files reports in the inbox. False is a dry run: it runs and logs only.",
    )


class SlackChannelScoutCreateResponseSerializer(serializers.Serializer):
    created = serializers.BooleanField(help_text="True when this request created the scout.")
    skill_name = serializers.CharField(
        help_text="The new scout's skill name, its permanent identifier. Its config records the Slack source as owner."
    )


class SlackChannelScoutViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Scouts that read chosen Slack channels from the data warehouse.

    Creation lives here rather than on the generic scout endpoint because the Slack source a scout reads is recorded
    on its config as its owner. This endpoint checks that the caller may read that source first.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_scout"
    required_scopes = ["llm_skill:write", "signal_scout:write", "external_data_source:read"]

    def _canonical_team(self) -> Team:
        # Scouts run on the canonical team, so the Slack tables are read from there too. A source on a child
        # environment would name tables the scout's run cannot see.
        return self.team.parent_team or self.team

    def _source_access(self, team: Team) -> UserAccessControl:
        access = UserAccessControl(user=cast(User, self.request.user), team=team)
        if not access.check_access_level_for_resource("external_data_source", "viewer"):
            raise exceptions.PermissionDenied("Reading Slack channels requires access to data warehouse sources.")
        return access

    @extend_schema(
        responses={200: SlackScoutChannelSourcesSerializer},
        summary="List Slack channels for scouts",
        description="The Slack data warehouse sources of this project and the channels each one syncs.",
    )
    @action(detail=False, methods=["get"], required_scopes=["external_data_source:read"])
    def channels(self, request: Request, **kwargs: Any) -> Response:
        team = self._canonical_team()
        self._source_access(team)
        sources = list_slack_channel_sources(team, cast(User, request.user))
        return Response(SlackScoutChannelSourcesSerializer({"sources": sources}).data)

    @validated_request(
        SlackChannelScoutCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=SlackChannelScoutCreateResponseSerializer, description="The scout was created."
            ),
            400: OpenApiResponse(description="The source, channels, or schedule are invalid."),
            403: OpenApiResponse(description="The caller may not create scouts or read data warehouse sources."),
        },
        summary="Create a Slack channel scout",
        description=(
            "Create a scout that reads the messages of the given Slack channels from the data warehouse and files "
            "inbox reports about the problems and requests people raise there. A scheduled run is skipped when "
            "none of the channels has a new message."
        ),
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        team = self._canonical_team()
        user = cast(User, request.user)
        self._source_access(team)
        validated = request.validated_data
        source_id = str(validated["source_id"])
        try:
            definition = plan_slack_channel_scout(
                team=team,
                user=user,
                source_id=source_id,
                channel_ids=validated["channel_ids"],
                steer=validated.get("steer", ""),
            )
        except SlackChannelSelectionError as error:
            raise exceptions.ValidationError({"channel_ids": str(error)})
        config_options: dict[str, Any] = {"emit": validated["emit"], "precheck_query": definition.precheck_query}
        if validated.get("run_cron_schedule"):
            config_options["run_cron_schedule"] = validated["run_cron_schedule"]
        # The facade checks the skill-authoring bar a scout needs, so this view only adds the warehouse read check.
        result = signals_facade.create_scout_for_source(
            team=team,
            user=user,
            display_name=validated["display_name"],
            description=definition.description,
            body=definition.body,
            files=[],
            config_options=config_options,
            request=request,
            serializer_context={"project_id": team.project_id, "team": team, "request": request},
            source_product=SLACK_SCOUT_SOURCE_PRODUCT,
            source_id=source_id,
        )
        report_user_action(
            user,
            "inbox_slack_channel_scout_created",
            {
                "channel_count": len(dict.fromkeys(validated["channel_ids"])),
                "has_steer": bool(validated.get("steer", "").strip()),
                "has_cron_schedule": bool(validated.get("run_cron_schedule")),
                "emit": validated["emit"],
            },
            team=self.team,
            request=request,
        )
        return Response(
            SlackChannelScoutCreateResponseSerializer(
                {"created": result.created, "skill_name": result.config.skill_name}
            ).data,
            status=status.HTTP_201_CREATED,
        )
