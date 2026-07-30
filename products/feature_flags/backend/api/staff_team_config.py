import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.permissions import IsStaffUser

from products.feature_flags.backend.api.staff_cache import _team_ids_field
from products.feature_flags.backend.models.team_feature_flags_config import TeamFeatureFlagsConfig

logger = structlog.get_logger(__name__)

# A starting bound, not load-tested. Kept distinct from staff_cache.py's MAX_TEAMS_PER_MUTATION:
# this caps a batch read, that caps a bulk mutation fan-out, and the two happen to share a
# value today by coincidence, not by requirement.
MAX_TEAM_IDS_PER_QUERY = 50


class StaffTeamConfigQuerySerializer(serializers.Serializer):
    team_ids = _team_ids_field(
        f"Team ids to report feature-flags team config for (max {MAX_TEAM_IDS_PER_QUERY} per request). "
        "Repeat the param (?team_ids=1&team_ids=2) or pass one comma-separated value (?team_ids=1,2).",
        max_length=MAX_TEAM_IDS_PER_QUERY,
    )


class StaffTeamConfigSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id.")
    minimal_flag_called_events = serializers.BooleanField(
        help_text=(
            "Whether this team's SDKs receive the slim $feature_flag_called event shape "
            "(omitting fields only needed for experiments) instead of the full legacy shape."
        )
    )


@extend_schema_serializer(many=False)
class StaffTeamConfigListResponseSerializer(serializers.Serializer):
    results = StaffTeamConfigSerializer(many=True, help_text="Per-team feature-flags config.")


class StaffTeamConfigMutationSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id to update. Exactly one team per request.")
    minimal_flag_called_events = serializers.BooleanField(
        help_text=(
            "New value for the team's minimal_flag_called_events setting. Only set true after "
            "confirming that team's SDK versions support the slim $feature_flag_called event shape."
        )
    )


class FeatureFlagsStaffTeamConfigViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped read/write for TeamFeatureFlagsConfig (currently just
    minimal_flag_called_events).

    Single-team writes only, by design: this setting is meant to be flipped one team at a time
    after staff manually verify that team's SDK versions support the slim $feature_flag_called
    event shape, unlike the cache tools' bulk rebuild/clear.

    Registered on the root router so it is not team-nested; staff act on teams they do not
    belong to, same as staff_cache.py / staff_teams.py.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    @validated_request(
        query_serializer=StaffTeamConfigQuerySerializer,
        responses={200: OpenApiResponse(response=StaffTeamConfigListResponseSerializer)},
    )
    def list(self, request: request.Request, **kwargs) -> response.Response:
        # Dedupe (preserving order) so a caller passing the same id twice doesn't get duplicate
        # rows in `results`, matching staff_cache.py's handling of team_ids.
        team_ids: list[int] = list(dict.fromkeys(request.validated_query_data["team_ids"]))
        existing_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
        config_by_team_id = dict(
            TeamFeatureFlagsConfig.objects.filter(team_id__in=team_ids).values_list(
                "team_id", "minimal_flag_called_events"
            )
        )
        results = [
            {"team_id": team_id, "minimal_flag_called_events": config_by_team_id.get(team_id, False)}
            for team_id in team_ids
            if team_id in existing_team_ids
        ]
        return response.Response({"results": results})

    @validated_request(
        request_serializer=StaffTeamConfigMutationSerializer,
        responses={200: OpenApiResponse(response=StaffTeamConfigSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def set(self, request: request.Request, **kwargs) -> response.Response:
        team_id: int = request.validated_data["team_id"]
        new_value: bool = request.validated_data["minimal_flag_called_events"]

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise NotFound(f"Team {team_id} not found.")

        config = get_or_create_team_extension(team, TeamFeatureFlagsConfig)
        old_value = config.minimal_flag_called_events
        config.minimal_flag_called_events = new_value
        config.save(update_fields=["minimal_flag_called_events"])

        # posthog.tasks.team_metadata sits under posthog.tasks, whose __init__ is a celery
        # autoimport aggregator that pulls in every task module — keep that off the API
        # router's import path by deferring it to call time. The local tasks module is
        # deferred for the same reason (it imports celery machinery).
        from posthog.tasks.team_metadata import update_team_metadata_cache_task  # noqa: PLC0415

        from products.feature_flags.backend.tasks import update_team_flags_cache  # noqa: PLC0415

        # /flags and /decide read this value out of team_metadata_hypercache, and local-eval
        # SDKs read it out of the flag-definitions blob — neither reads the DB, so the write
        # above has no effect until both caches are rebuilt.
        update_team_metadata_cache_task.delay(team.id)
        update_team_flags_cache.delay(team.id)

        logger.info(
            "flags_staff_team_config_updated",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            team_id=team.id,
            old_value=old_value,
            new_value=new_value,
        )

        return response.Response({"team_id": team.id, "minimal_flag_called_events": new_value})
