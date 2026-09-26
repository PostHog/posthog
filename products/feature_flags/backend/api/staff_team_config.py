from typing import Any

from django.db import transaction
from django.db.models import Count

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import validated_request
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.permissions import IsStaffUser

from products.feature_flags.backend.api.staff_cache import _team_ids_field
from products.feature_flags.backend.flag_evaluations_mode import (
    OrganizationModeChange,
    UnknownIdsError,
    get_organizations_of_teams,
    set_organization_flag_evaluations_mode,
)
from products.feature_flags.backend.flag_limits import (
    get_max_feature_flags_override_for_team,
    resolve_max_feature_flags,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flags_config import (
    MAX_FEATURE_FLAGS_OVERRIDE_CEILING,
    FlagEvaluationsMode,
    PropertyMatchingVersion,
    TeamFeatureFlagsConfig,
)

logger = structlog.get_logger(__name__)

# A starting bound, not load-tested. Kept distinct from staff_cache.py's MAX_TEAMS_PER_MUTATION:
# this caps a batch read, that caps a bulk mutation fan-out, and the two happen to share a
# value today by coincidence, not by requirement.
MAX_TEAM_IDS_PER_QUERY = 50

# Caps the team ids of one flag_evaluations_mode write. The write runs in one transaction with one
# savepoint per organization, and each team id adds at most one organization.
MAX_IDS_PER_MODE_WRITE = 50

MUTABLE_SETTINGS = (
    "minimal_flag_called_events",
    "property_matching_version",
    "max_feature_flags_override",
)


def _config_row(
    *,
    team_id: int,
    minimal_flag_called_events: bool,
    property_matching_version: int,
    max_feature_flags_override: int | None,
    flag_evaluations_mode: int,
    feature_flag_count: int,
) -> dict[str, Any]:
    """Build the row shape shared by list() and set(), which both feed the same staff tools table."""
    return {
        "team_id": team_id,
        "minimal_flag_called_events": minimal_flag_called_events,
        "property_matching_version": property_matching_version,
        "max_feature_flags_override": max_feature_flags_override,
        "effective_max_feature_flags": resolve_max_feature_flags(max_feature_flags_override),
        "flag_evaluations_mode": flag_evaluations_mode,
        "feature_flag_count": feature_flag_count,
    }


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
    property_matching_version = serializers.ChoiceField(
        choices=PropertyMatchingVersion.choices,
        help_text="Property matching semantics used by /flags, local evaluation, and cohort generation.",
    )
    max_feature_flags_override = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Per-team override for the maximum number of feature flags this team may create, "
            "or null when the team uses the global default."
        ),
    )
    effective_max_feature_flags = serializers.IntegerField(
        help_text=(
            "The flag-count limit actually enforced for this team: the override when one is set, "
            "otherwise the global MAX_FEATURE_FLAGS_PER_TEAM setting."
        )
    )
    flag_evaluations_mode = serializers.ChoiceField(
        choices=FlagEvaluationsMode.choices,
        help_text=(
            "Which table this team's $feature_flag_called data is read from. 0 reads events, 1 and 2 read "
            "flag_evaluations. 2 is reserved for ingestion to stop writing $feature_flag_called to events. "
            "Ingestion ignores 2 until that support deploys, so 2 acts as 1 until then."
        ),
    )
    feature_flag_count = serializers.IntegerField(
        help_text=(
            "Number of feature flags the team has today, excluding soft-deleted ones, counted the "
            "same way the limit is enforced."
        )
    )


@extend_schema_serializer(many=False)
class StaffTeamConfigListResponseSerializer(serializers.Serializer):
    results = StaffTeamConfigSerializer(many=True, help_text="Per-team feature-flags config.")


class StaffTeamConfigMutationSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id to update. Exactly one team per request.")
    minimal_flag_called_events = serializers.BooleanField(
        required=False,
        help_text=(
            "New value for the team's minimal_flag_called_events setting. Omit to leave it "
            "unchanged. Only set true after confirming that team's SDK versions support the slim "
            "$feature_flag_called event shape."
        ),
    )
    property_matching_version = serializers.ChoiceField(
        choices=PropertyMatchingVersion.choices,
        required=False,
        help_text=(
            "New property matching version for the team. Version 1 preserves legacy behavior. "
            "Version 2 uses explicit scalar and array equality. Only set version 2 after confirming "
            "that the team's local-evaluation SDK versions support it. Omit to leave it unchanged."
        ),
    )
    max_feature_flags_override = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=MAX_FEATURE_FLAGS_OVERRIDE_CEILING,
        help_text=(
            f"New per-team flag-count limit (1-{MAX_FEATURE_FLAGS_OVERRIDE_CEILING:,}). Send null "
            "to clear the override so the team falls back to the global default. Omit to leave it "
            "unchanged."
        ),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not attrs.keys() & MUTABLE_SETTINGS:
            raise serializers.ValidationError("Provide at least one setting to update.")
        return attrs


class StaffFlagEvaluationsModeMutationSerializer(serializers.Serializer):
    flag_evaluations_mode = serializers.ChoiceField(
        choices=FlagEvaluationsMode.choices,
        help_text=(
            "Target flag_evaluations mode. 0 reads events, 1 reads flag_evaluations, 2 also stops writing "
            "$feature_flag_called to events. Ingestion ignores 2 until its support for 2 deploys, so 2 acts "
            "as 1 until then."
        ),
    )
    team_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=MAX_IDS_PER_MODE_WRITE,
        help_text=(
            f"Teams to move (max {MAX_IDS_PER_MODE_WRITE}). Other teams of their organizations keep their "
            "mode unless whole_organizations is set."
        ),
    )
    whole_organizations = serializers.BooleanField(
        default=False,
        help_text="Also move every other team of each organization that owns one of the teams.",
    )
    allow_downgrade = serializers.BooleanField(
        default=False,
        help_text=(
            "Also lower teams that are above the target mode. Once ingestion acts on mode 2, lowering a "
            "team from 2 leaves a gap in the events table for the time the team spent on 2."
        ),
    )
    dry_run = serializers.BooleanField(
        default=False,
        help_text="Report what the write would change, and write nothing.",
    )


@extend_schema_serializer(component_name="StaffOrganizationModeChange")
class StaffOrganizationModeChangeSerializer(DataclassSerializer):
    class Meta:
        dataclass = OrganizationModeChange
        exclude = ["organization_created_at"]
        extra_kwargs = {
            "organization_id": {"help_text": "Organization id."},
            "organization_name": {"help_text": "Organization name."},
            "organization_team_count": {
                "help_text": "Every team of the organization, including teams the request does not cover."
            },
            "team_count": {
                "help_text": "Teams of this organization that the request covers. The counts below are over these teams."
            },
            "teams_below_mode": {"help_text": "Covered teams below the target mode."},
            "teams_at_mode": {"help_text": "Covered teams already on the target mode."},
            "teams_above_mode": {
                "help_text": "Covered teams above the target mode. They move only when allow_downgrade is set."
            },
            "teams_changed": {"help_text": "Teams the write moved to the target mode, or would move on a dry run."},
            "teams_left_above_mode": {
                "help_text": "Covered teams above the target mode that the write leaves there, because allow_downgrade is not set."
            },
        }


class StaffFlagEvaluationsModeResponseSerializer(serializers.Serializer):
    flag_evaluations_mode = serializers.ChoiceField(
        choices=FlagEvaluationsMode.choices, help_text="The target mode of the request."
    )
    dry_run = serializers.BooleanField(help_text="True when the request wrote nothing.")
    organizations = StaffOrganizationModeChangeSerializer(
        many=True, help_text="One entry per organization the request covers, oldest organization first."
    )


class FeatureFlagsStaffTeamConfigViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped read/write for TeamFeatureFlagsConfig: behavior rollout gates and the
    per-team feature-flag count override.

    set() writes one team only, by design. Rollout settings are changed after staff verify SDK
    compatibility, and max_feature_flags_override is a per-customer capacity grant. Neither is a
    bulk operation, unlike the cache tools' rebuild and clear. flag_evaluations_mode is meant to be
    uniform across an organization, so only set_flag_evaluations_mode() writes it, for many teams or
    whole organizations at once. It uses the same helpers as the set_flag_evaluations_mode command,
    including the guard against lowering a team, and it writes every organization of a request in
    one transaction.

    set() takes partial updates: omit a setting to leave it unchanged, and send
    max_feature_flags_override as null to clear the override.

    Registered on the root router so it is not team-nested; staff act on teams they do not
    belong to, same as staff_cache.py / staff_teams.py.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]
    # set() distinguishes an absent setting from one sent explicitly, and DRF's BooleanField
    # materializes an absent field as False for form-encoded bodies (see default_empty_html in
    # rest_framework/fields.py). Under FormParser a request meaning to set only the flag limit
    # would therefore also switch minimal_flag_called_events off, so restrict this to JSON.
    parser_classes = [JSONParser]

    @validated_request(
        query_serializer=StaffTeamConfigQuerySerializer,
        responses={200: OpenApiResponse(response=StaffTeamConfigListResponseSerializer)},
    )
    def list(self, request: request.Request, **kwargs) -> response.Response:
        # Dedupe (preserving order) so a caller passing the same id twice doesn't get duplicate
        # rows in `results`, matching staff_cache.py's handling of team_ids.
        team_ids: list[int] = list(dict.fromkeys(request.validated_query_data["team_ids"]))
        # Each team maps to its project root. The override and the flag count are both
        # project-scoped: check_flag_limits_for_team reads the override off the root
        # (get_max_feature_flags_override_for_team) and counts through FeatureFlag.objects, whose
        # RootTeamManager rewrites team_id= to the root. Reading either off the environment team
        # would show a limit the validator does not enforce.
        root_team_id_by_team_id = {
            team_id: parent_team_id or team_id
            for team_id, parent_team_id in Team.objects.filter(id__in=team_ids).values_list("id", "parent_team_id")
        }
        root_team_ids = set(root_team_id_by_team_id.values())
        # Behavior rollouts stay per-team because evaluation readers key on the literal team, so
        # they come from each team's row. The capacity override comes from the project root.
        config_by_team_id = TeamFeatureFlagsConfig.objects.in_bulk(team_ids)
        override_by_root_team_id = dict(
            TeamFeatureFlagsConfig.objects.filter(team_id__in=root_team_ids).values_list(
                "team_id", "max_feature_flags_override"
            )
        )
        # FeatureFlag.objects excludes soft-deleted rows, so counting the root team gives the
        # number check_flag_limits_for_team compares against the limit. Staff reading this number
        # next to the limit have to see the number the validator sees.
        flag_count_by_root_team_id = dict(
            FeatureFlag.objects.filter(team_id__in=root_team_ids)
            .values("team_id")
            .annotate(count=Count("id"))
            .values_list("team_id", "count")
        )

        results = []
        for team_id in team_ids:
            if team_id not in root_team_id_by_team_id:
                continue
            root_team_id = root_team_id_by_team_id[team_id]
            # An unsaved instance stands in for a legacy team whose row predates this extension,
            # so the model's own field defaults answer for it rather than a second copy here.
            config = config_by_team_id.get(team_id) or TeamFeatureFlagsConfig()
            results.append(
                _config_row(
                    team_id=team_id,
                    minimal_flag_called_events=config.minimal_flag_called_events,
                    property_matching_version=config.property_matching_version,
                    max_feature_flags_override=override_by_root_team_id.get(root_team_id),
                    flag_evaluations_mode=config.flag_evaluations_mode,
                    feature_flag_count=flag_count_by_root_team_id.get(root_team_id, 0),
                )
            )
        return response.Response({"results": results})

    @validated_request(
        request_serializer=StaffTeamConfigMutationSerializer,
        responses={200: OpenApiResponse(response=StaffTeamConfigSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def set(self, request: request.Request, **kwargs) -> response.Response:
        validated = request.validated_data
        team_id: int = validated["team_id"]

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise NotFound(f"Team {team_id} not found.")

        # The limit is enforced against the project's whole flag set, and get_max_feature_flags_for_team
        # reads the override off the project root, so a row written here would never be read.
        # Behavior rollouts stay per-team because evaluation readers key on the literal team. This
        # is why only the capacity override is refused rather than the whole request.
        if "max_feature_flags_override" in validated and team.parent_team_id is not None:
            raise serializers.ValidationError(
                f"Team {team_id} is an environment of project {team.parent_team_id}. Set the flag limit on "
                f"team {team.parent_team_id}: it is enforced against the whole project's flags."
            )

        config = get_or_create_team_extension(team, TeamFeatureFlagsConfig)
        old_minimal_flag_called_events = config.minimal_flag_called_events
        old_property_matching_version = config.property_matching_version
        old_max_feature_flags_override = config.max_feature_flags_override

        # Saving only the fields actually sent keeps two staff editing different settings on the
        # same team from overwriting each other.
        update_fields = [setting for setting in MUTABLE_SETTINGS if setting in validated]
        for setting in update_fields:
            setattr(config, setting, validated[setting])
        config.save(update_fields=update_fields)

        if {"minimal_flag_called_events", "property_matching_version"} & validated.keys():
            # posthog.tasks.team_metadata sits under posthog.tasks, whose __init__ is a celery
            # autoimport aggregator that pulls in every task module — keep that off the API
            # router's import path by deferring it to call time. The local tasks module is
            # deferred for the same reason (it imports celery machinery).
            from posthog.tasks.team_metadata import update_team_metadata_cache_task  # noqa: PLC0415

            from products.feature_flags.backend.tasks import update_team_flags_cache  # noqa: PLC0415

            # /flags and /decide read this value out of team_metadata_hypercache, and local-eval
            # SDKs read it out of the flag-definitions blob, so the write above has no effect
            # until both caches are rebuilt. Re-sending an unchanged value rebuilds them anyway,
            # which is the way back from a failed cache write.
            update_team_metadata_cache_task.delay(team.id)
            update_team_flags_cache.delay(team.id)

        # old_value/new_value stay bound to minimal_flag_called_events under those names because
        # dashboards outside this repo were built on them before the endpoint took a second setting.
        changed_values: dict[str, Any] = {}
        if "minimal_flag_called_events" in validated:
            changed_values["old_value"] = old_minimal_flag_called_events
            changed_values["new_value"] = config.minimal_flag_called_events
        if "property_matching_version" in validated:
            changed_values["old_property_matching_version"] = old_property_matching_version
            changed_values["new_property_matching_version"] = config.property_matching_version
        if "max_feature_flags_override" in validated:
            changed_values["old_max_feature_flags_override"] = old_max_feature_flags_override
            changed_values["new_max_feature_flags_override"] = config.max_feature_flags_override

        logger.info(
            "flags_staff_team_config_updated",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            team_id=team.id,
            updated_fields=update_fields,
            **changed_values,
        )

        # The row has to show the root's override, matching list() and the validator. A root team's
        # own config is already that, and an environment team reaches here only for rollout edits,
        # since the override write is refused above.
        return response.Response(
            _config_row(
                team_id=team.id,
                minimal_flag_called_events=config.minimal_flag_called_events,
                property_matching_version=config.property_matching_version,
                max_feature_flags_override=(
                    config.max_feature_flags_override
                    if team.parent_team_id is None
                    else get_max_feature_flags_override_for_team(team.parent_team_id)
                ),
                flag_evaluations_mode=config.flag_evaluations_mode,
                feature_flag_count=FeatureFlag.objects.filter(team_id=team.id).count(),
            )
        )

    @validated_request(
        request_serializer=StaffFlagEvaluationsModeMutationSerializer,
        responses={200: OpenApiResponse(response=StaffFlagEvaluationsModeResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def set_flag_evaluations_mode(self, request: request.Request, **kwargs) -> response.Response:
        validated = request.validated_data
        mode = FlagEvaluationsMode(validated["flag_evaluations_mode"])
        allow_downgrade: bool = validated["allow_downgrade"]
        dry_run: bool = validated["dry_run"]

        team_ids: list[int] = validated["team_ids"]
        whole_organizations: bool = validated["whole_organizations"]
        try:
            organizations = get_organizations_of_teams(team_ids)
        except UnknownIdsError as error:
            raise NotFound(str(error)) from error

        # One transaction across organizations, so the request applies in full or not at all.
        with transaction.atomic():
            changes = [
                set_organization_flag_evaluations_mode(
                    organization,
                    mode,
                    allow_downgrade=allow_downgrade,
                    dry_run=dry_run,
                    team_ids=None if whole_organizations else team_ids,
                )
                for organization in organizations
            ]

        if not dry_run:
            logger.info(
                "flags_staff_flag_evaluations_mode_updated",
                staff_user_id=request.user.id,
                was_impersonated=is_impersonated(request),
                flag_evaluations_mode=mode.value,
                allow_downgrade=allow_downgrade,
                team_ids=team_ids,
                whole_organizations=whole_organizations,
                organization_ids=[str(organization.id) for organization in organizations],
                teams_changed=sum(change.teams_changed for change in changes),
            )

        return response.Response(
            StaffFlagEvaluationsModeResponseSerializer(
                {"flag_evaluations_mode": mode.value, "dry_run": dry_run, "organizations": changes}
            ).data
        )
