from collections.abc import Callable
from typing import Any

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema_field, extend_schema_serializer
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team import Team
from posthog.permissions import IsStaffUser

from products.feature_flags.backend.flags_cache import enqueue_evaluation_cache_invalidation, flags_hypercache
from products.feature_flags.backend.local_evaluation import (
    flag_definitions_hypercache,
    flag_definitions_without_cohorts_hypercache,
)
from products.feature_flags.backend.tasks import (
    clear_team_definitions_cache,
    clear_team_evaluation_cache,
    update_team_flags_cache,
)

logger = structlog.get_logger(__name__)

# A starting bound, not load-tested. Rebuild/clear act on every listed team, so this caps how
# much work a single staff request can trigger; adjust if it proves too tight.
MAX_TEAMS_PER_MUTATION = 50

EVALUATION = "evaluation"
DEFINITIONS = "definitions"
DEFINITIONS_NO_COHORTS = "definitions_no_cohorts"

# What rebuild/clear act on. "definitions" already rebuilds/clears both definitions-cache
# variants together (see update_flag_caches / clear_flag_definition_caches), so there is no
# separate mutation target for the no-cohorts variant.
CACHE_CHOICES = [EVALUATION, DEFINITIONS]

# The readable caches, enumerated once here rather than hardcoded in list/entry.
_READABLE_HYPERCACHES = {
    EVALUATION: flags_hypercache,
    DEFINITIONS: flag_definitions_hypercache,
    DEFINITIONS_NO_COHORTS: flag_definitions_without_cohorts_hypercache,
}

# What status/entry can read. Unlike mutation, status/entry read each definitions-cache
# variant independently, so the no-cohorts variant is separately observable here.
READABLE_CACHE_CHOICES = list(_READABLE_HYPERCACHES)


def _team_ids_field(help_text: str) -> serializers.ListField:
    return serializers.ListField(
        child=serializers.IntegerField(), max_length=MAX_TEAMS_PER_MUTATION, help_text=help_text
    )


class StaffCacheStatusQuerySerializer(serializers.Serializer):
    team_ids = _team_ids_field(
        f"Team ids to report cache status for (max {MAX_TEAMS_PER_MUTATION} per request). "
        "Repeat the param, e.g. ?team_ids=1&team_ids=2."
    )


def _cache_source_field() -> serializers.ChoiceField:
    return serializers.ChoiceField(
        choices=["redis", "miss"],
        help_text="'redis' when a warm entry is cached, or 'miss' when nothing is cached in Redis.",
    )


class StaffCacheEntryStatusSerializer(serializers.Serializer):
    source = _cache_source_field()  # type: ignore[assignment]
    flag_count = serializers.IntegerField(
        allow_null=True,
        help_text="Number of flags in the cached payload, or null on a miss.",
    )


class StaffCacheTeamStatusSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id.")
    evaluation = StaffCacheEntryStatusSerializer(help_text="Status of the /flags evaluation cache.")
    definitions = StaffCacheEntryStatusSerializer(
        help_text="Status of the /flags/definitions local-eval cache (with-cohorts variant)."
    )
    definitions_no_cohorts = StaffCacheEntryStatusSerializer(
        help_text=(
            "Status of the /flags/definitions local-eval cache (without-cohorts variant, cohort "
            "filters transformed to properties for simple SDK clients)."
        )
    )


@extend_schema_serializer(many=False)
class StaffCacheStatusResponseSerializer(serializers.Serializer):
    results = StaffCacheTeamStatusSerializer(many=True, help_text="Per-team cache status.")


class StaffCacheMutationSerializer(serializers.Serializer):
    team_ids = _team_ids_field(f"Team ids to act on (max {MAX_TEAMS_PER_MUTATION} per request).")
    caches = serializers.ListField(
        child=serializers.ChoiceField(choices=CACHE_CHOICES),
        required=False,
        default=CACHE_CHOICES,
        help_text=(
            "Which logical caches to act on: 'evaluation' (the /flags cache) and/or 'definitions' "
            "(the /flags/definitions local-eval cache). Defaults to both."
        ),
    )


class StaffCacheMutationResponseSerializer(serializers.Serializer):
    queued_team_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Team ids for which the requested action's tasks were enqueued.",
    )
    not_found_team_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Requested team ids that do not exist.",
    )


class StaffCacheEntryQuerySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id to fetch the cache entry for.")
    cache = serializers.ChoiceField(
        choices=READABLE_CACHE_CHOICES,
        help_text=(
            "Which cache to fetch: 'evaluation' (the /flags cache), 'definitions' (the "
            "/flags/definitions local-eval cache, with-cohorts variant), or 'definitions_no_cohorts' "
            "(the without-cohorts variant served to simple SDK clients)."
        ),
    )


@extend_schema_field(OpenApiTypes.OBJECT)
class StaffCacheEntryDataField(serializers.JSONField):
    """Raw cache payload; shape mirrors the /flags or /flags/definitions response for the team."""


class StaffCacheEntryResponseSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="Team id.")
    cache = serializers.ChoiceField(choices=READABLE_CACHE_CHOICES, help_text="Which cache this entry is for.")
    source = _cache_source_field()  # type: ignore[assignment]
    data = StaffCacheEntryDataField(  # type: ignore[assignment]
        allow_null=True,
        help_text="Raw cached payload as stored in Redis, or null on a miss.",
    )


def _entry_status(entry: tuple[dict | None, str, str | None]) -> dict[str, Any]:
    """Turn a batch_get_from_cache tuple into the reported {source, flag_count}.

    Status is read Redis-only via batch_get_from_cache (the same side-effect-free read the
    verifiers use): a plain get_from_cache_with_source would trigger a live DB rebuild as a side
    effect of merely viewing status, repopulating the very cache the staff member is inspecting and
    making "miss" unobservable. Redis is the hot path the flags service actually reads, so "warm in
    redis" is the meaningful signal. A redis hit whose stored payload is empty yields data None;
    report that as a miss too since there are no flags to count.
    """
    data, source, _etag = entry
    if data is None:
        return {"source": "miss", "flag_count": None}
    return {"source": source, "flag_count": len(data.get("flags", []))}


def _dispatch_mutation(
    request: request.Request,
    team_ids: list[int],
    caches: list[str],
    *,
    evaluation_fn: Callable[[int], None],
    definitions_fn: Callable[[int], None],
    log_event: str,
) -> response.Response:
    """Shared shape of `rebuild` and `clear`: split team_ids into found/not-found, dispatch the
    per-cache action for each found team, log, and return the 202 response both actions share."""
    # Dedupe (preserving order) so a caller passing the same id twice doesn't enqueue duplicate
    # rebuild/clear work for that team.
    deduped_ids = list(dict.fromkeys(team_ids))
    found_set = set(Team.objects.filter(id__in=deduped_ids).values_list("id", flat=True))
    found_ids = [team_id for team_id in deduped_ids if team_id in found_set]
    not_found_ids = [team_id for team_id in deduped_ids if team_id not in found_set]

    for team_id in found_ids:
        if EVALUATION in caches:
            evaluation_fn(team_id)
        if DEFINITIONS in caches:
            definitions_fn(team_id)

    logger.info(
        log_event,
        staff_user_id=request.user.id,
        was_impersonated=is_impersonated(request),
        team_ids=found_ids,
        not_found_team_ids=not_found_ids,
        caches=caches,
    )

    return response.Response(
        {"queued_team_ids": found_ids, "not_found_team_ids": not_found_ids},
        status=status.HTTP_202_ACCEPTED,
    )


class FeatureFlagsStaffCacheViewSet(viewsets.ViewSet):
    """
    Staff-only, unscoped status/entry/rebuild/clear for the HyperCache-backed flag caches.

    Rebuild/clear act on two logical targets ('evaluation' and 'definitions'; the latter rebuilds
    or clears both definitions-cache variants together). Status/entry can read a third, narrower
    target ('definitions_no_cohorts') independently, since the two definitions-cache variants are
    individually readable even though they're only mutated as a pair.

    Reuses the existing cache functions and Celery tasks (the same mechanism signal handlers use
    when a flag changes) rather than re-implementing cache-write logic. Registered on the root
    router so it is not team-nested; staff act on teams they do not belong to.
    """

    # Not part of the public API scope model: access is gated entirely by IsStaffUser below,
    # not by a personal-API-key scope, so this stays out of the public OpenAPI/generated-client
    # surface (see posthog/api/documentation.py's INTERNAL handling).
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, IsStaffUser]

    @validated_request(
        query_serializer=StaffCacheStatusQuerySerializer,
        responses={200: OpenApiResponse(response=StaffCacheStatusResponseSerializer)},
    )
    def list(self, request: request.Request, **kwargs) -> response.Response:
        # Dedupe (preserving order) so a caller passing the same id twice doesn't get duplicate
        # rows in `results`, matching _dispatch_mutation's handling of team_ids below.
        team_ids: list[int] = list(dict.fromkeys(request.validated_query_data["team_ids"]))
        teams_by_id = {team.id: team for team in Team.objects.filter(id__in=team_ids)}
        teams = [teams_by_id[team_id] for team_id in team_ids if team_id in teams_by_id]

        # One Redis MGET per cache across all teams, rather than one per (team, cache).
        batches = {kind: hypercache.batch_get_from_cache(teams) for kind, hypercache in _READABLE_HYPERCACHES.items()}

        results = [
            {
                "team_id": team.id,
                "evaluation": _entry_status(batches[EVALUATION][team.id]),
                "definitions": _entry_status(batches[DEFINITIONS][team.id]),
                "definitions_no_cohorts": _entry_status(batches[DEFINITIONS_NO_COHORTS][team.id]),
            }
            for team in teams
        ]

        return response.Response({"results": results})

    @validated_request(
        request_serializer=StaffCacheMutationSerializer,
        responses={202: OpenApiResponse(response=StaffCacheMutationResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def rebuild(self, request: request.Request, **kwargs) -> response.Response:
        # Evaluation cache goes through enqueue_evaluation_cache_invalidation, raising the same
        # invalidation signal (Kafka dual-write + Celery) an organic flag create/update/delete
        # raises, rather than a staff-only side channel.
        return _dispatch_mutation(
            request,
            request.validated_data["team_ids"],
            request.validated_data["caches"],
            evaluation_fn=enqueue_evaluation_cache_invalidation,
            definitions_fn=update_team_flags_cache.delay,
            log_event="flags_staff_cache_rebuild",
        )

    @validated_request(
        query_serializer=StaffCacheEntryQuerySerializer,
        responses={200: OpenApiResponse(response=StaffCacheEntryResponseSerializer)},
    )
    @action(methods=["GET"], detail=False)
    def entry(self, request: request.Request, **kwargs) -> response.Response:
        team_id: int = request.validated_query_data["team_id"]
        cache_kind: str = request.validated_query_data["cache"]

        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise NotFound(f"Team {team_id} not found.")

        hypercache = _READABLE_HYPERCACHES[cache_kind]
        cache_entry = hypercache.batch_get_from_cache([team])[team.id]
        data, _, _etag = cache_entry
        # _entry_status reports a redis hit whose stored payload is empty as a miss, same as a
        # genuine cache miss, so entry() agrees with what list() shows for the same team/cache.
        source = _entry_status(cache_entry)["source"]

        logger.info(
            "flags_staff_cache_entry_viewed",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            team_id=team_id,
            cache=cache_kind,
        )

        return response.Response({"team_id": team_id, "cache": cache_kind, "source": source, "data": data})

    @validated_request(
        request_serializer=StaffCacheMutationSerializer,
        responses={202: OpenApiResponse(response=StaffCacheMutationResponseSerializer)},
    )
    @action(methods=["POST"], detail=False)
    def clear(self, request: request.Request, **kwargs) -> response.Response:
        # No shared invalidation signal to raise here, unlike rebuild: the Kafka message is
        # defined as an "invalidate/rebuild" trigger with no delete semantic, so this goes
        # straight to the cache-clearing tasks instead of enqueue_evaluation_cache_invalidation.
        return _dispatch_mutation(
            request,
            request.validated_data["team_ids"],
            request.validated_data["caches"],
            evaluation_fn=clear_team_evaluation_cache.delay,
            definitions_fn=clear_team_definitions_cache.delay,
            log_event="flags_staff_cache_clear",
        )
