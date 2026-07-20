import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import BaseCache

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field, extend_schema_serializer
from rest_framework import request, response, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.mixins import validated_request
from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.helpers.impersonation import is_impersonated
from posthog.models.team import Team
from posthog.permissions import IsStaffUser

from products.feature_flags.backend.flags_cache import enqueue_evaluation_cache_invalidation, flags_hypercache
from products.feature_flags.backend.local_evaluation import flag_definitions_hypercache
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

CACHE_CHOICES = [EVALUATION, DEFINITIONS]

# The readable caches, enumerated once here rather than hardcoded in list/entry.
_READABLE_HYPERCACHES = {
    EVALUATION: flags_hypercache,
    DEFINITIONS: flag_definitions_hypercache,
}

# Warm-all run status, published to the flags Redis by the Rust warmer
# (rust/feature-flags/src/flags/warm_run_status.rs). Keys, field names, states,
# and the staleness threshold are a contract with that module — change in lockstep.
WARM_RUN_STATUS_CACHE_KEY = "feature_flags/warm_run/status"
WARM_RUN_CANCEL_CACHE_KEY = "feature_flags/warm_run/cancel"
WARM_RUN_HEARTBEAT_STALE_SECONDS = 120
WARM_RUN_CANCEL_TTL_SECONDS = 3600

WARM_RUN_STATES = ["running", "completed", "cancelled"]
WARM_RUN_SCOPES = ["all_teams", "teams_with_flags"]

# Reading and mutating currently share the same choice set.
READABLE_CACHE_CHOICES = CACHE_CHOICES


class _RepeatedOrCommaSeparatedListField(serializers.ListField):
    """A ListField for query params that accepts values either as repeated keys
    (?team_ids=1&team_ids=2) or as a single comma-separated value (?team_ids=1,2). The latter is
    how our generated TS client (and plain URLSearchParams) serializes a number[] query param, so
    without this a caller using the generated client gets a validation error. Matches the
    repeated-or-comma-separated handling already used for query params elsewhere, e.g. the
    `include` param in posthog/api/element.py.
    """

    def get_value(self, dictionary: Any) -> Any:
        value = super().get_value(dictionary)
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str) and "," in value[0]:
            return value[0].split(",")
        return value


def _team_ids_field(help_text: str, *, max_length: int = MAX_TEAMS_PER_MUTATION) -> serializers.ListField:
    return _RepeatedOrCommaSeparatedListField(
        child=serializers.IntegerField(), max_length=max_length, help_text=help_text
    )


class StaffCacheStatusQuerySerializer(serializers.Serializer):
    team_ids = _team_ids_field(
        f"Team ids to report cache status for (max {MAX_TEAMS_PER_MUTATION} per request). "
        "Repeat the param (?team_ids=1&team_ids=2) or pass one comma-separated value (?team_ids=1,2)."
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
    definitions = StaffCacheEntryStatusSerializer(help_text="Status of the /flags/definitions local-eval cache.")


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
            "Which cache to fetch: 'evaluation' (the /flags cache) or 'definitions' "
            "(the /flags/definitions local-eval cache)."
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


class StaffWarmRunSerializer(serializers.Serializer):
    run_id = serializers.CharField(help_text="Unique id of the warm-all run.")
    state = serializers.ChoiceField(
        choices=WARM_RUN_STATES,
        help_text=(
            "'running' while the warmer is working, 'completed' when it finished (per-team failures "
            "are counted, not fatal), or 'cancelled' when a cancel request was honored."
        ),
    )
    scope = serializers.ChoiceField(
        choices=WARM_RUN_SCOPES,
        help_text="Which teams the run covers: every team, or only teams that have ever had a flag.",
    )
    total = serializers.IntegerField(help_text="Number of teams the run will warm.")
    processed = serializers.IntegerField(help_text="Teams processed so far (successful + failed).")
    successful = serializers.IntegerField(help_text="Teams whose evaluation cache was rebuilt successfully.")
    failed = serializers.IntegerField(help_text="Teams whose rebuild failed; details are in the warmer's logs.")
    last_team_id = serializers.IntegerField(
        allow_null=True,
        help_text="Highest team id dispatched so far — a resume cursor for operators re-running the warmer.",
    )
    started_at = serializers.DateTimeField(help_text="When the run started.")
    updated_at = serializers.DateTimeField(help_text="Heartbeat: last time the warmer reported progress.")
    is_stale = serializers.BooleanField(
        help_text=(
            "True when the run claims to be running but its heartbeat stopped — the warmer process "
            "likely died without writing a final state."
        )
    )
    cancel_requested = serializers.BooleanField(
        help_text="True when a cancel has been requested for this run but the warmer has not yet honored it."
    )


@extend_schema_serializer(many=False)
class StaffWarmRunResponseSerializer(serializers.Serializer):
    run = StaffWarmRunSerializer(
        allow_null=True,
        help_text="Most recent warm-all run, or null when none has been recorded (or the dedicated flags cache is not configured).",
    )


class StaffWarmRunCancelResponseSerializer(serializers.Serializer):
    run_id = serializers.CharField(help_text="Id of the run the cancel request targets.")
    cancel_requested = serializers.BooleanField(help_text="Always true on success.")


def _flags_dedicated_cache() -> Optional[BaseCache]:
    """The dedicated flags Redis as a Django cache, or None when not configured.

    Its config (pickle serializer + zstd compressor + 'posthog' key prefix) mirrors the Rust
    warmer's Redis client defaults, so both sides read each other's values transparently.
    """
    if FLAGS_DEDICATED_CACHE_ALIAS not in settings.CACHES:
        return None
    return caches[FLAGS_DEDICATED_CACHE_ALIAS]


def _parse_warm_run_status(raw: Optional[str]) -> Optional[dict[str, Any]]:
    """Parse the warmer's raw status blob, or None when absent/unreadable.

    Tolerant of malformed blobs (e.g. written by a newer binary): any parse failure reads as
    "no run" rather than a 500 on the staff page.
    """
    if raw is None:
        return None
    try:
        run = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("flags_staff_warm_run_status_unparseable")
        return None
    if (
        not isinstance(run, dict)
        or not isinstance(run.get("run_id"), str)
        or run.get("state") not in WARM_RUN_STATES
        or run.get("scope") not in WARM_RUN_SCOPES
    ):
        logger.warning("flags_staff_warm_run_status_malformed")
        return None
    return run


def _as_epoch(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _present_warm_run(run: dict[str, Any], cancel_run_id: Optional[str]) -> dict[str, Any]:
    """Convert the wire blob (epoch-second timestamps) into the API shape."""
    updated_at = _as_epoch(run.get("updated_at"))
    is_stale = run["state"] == "running" and time.time() - updated_at > WARM_RUN_HEARTBEAT_STALE_SECONDS
    return {
        "run_id": run["run_id"],
        "state": run["state"],
        "scope": run.get("scope"),
        "total": run.get("total", 0),
        "processed": run.get("processed", 0),
        "successful": run.get("successful", 0),
        "failed": run.get("failed", 0),
        "last_team_id": run.get("last_team_id"),
        "started_at": datetime.fromtimestamp(_as_epoch(run.get("started_at")), tz=UTC).isoformat(),
        "updated_at": datetime.fromtimestamp(updated_at, tz=UTC).isoformat(),
        "is_stale": is_stale,
        "cancel_requested": cancel_run_id == run["run_id"],
    }


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

    Rebuild/clear act on two logical targets: 'evaluation' (the /flags cache) and 'definitions'
    (the /flags/definitions local-eval cache), independently readable and mutable.

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

    @extend_schema(responses={200: OpenApiResponse(response=StaffWarmRunResponseSerializer)})
    @action(methods=["GET"], detail=False)
    def warm_run(self, request: request.Request, **kwargs) -> response.Response:
        """Status of the most recent warm-all run, published by the Rust warmer."""
        cache = _flags_dedicated_cache()
        if cache is None:
            return response.Response({"run": None})

        # One MGET for both keys, since this endpoint is polled every 5-30s per open staff page.
        values = cache.get_many([WARM_RUN_STATUS_CACHE_KEY, WARM_RUN_CANCEL_CACHE_KEY])
        run = _parse_warm_run_status(values.get(WARM_RUN_STATUS_CACHE_KEY))
        if run is None:
            return response.Response({"run": None})

        try:
            presented = _present_warm_run(run, values.get(WARM_RUN_CANCEL_CACHE_KEY))
        except (OverflowError, OSError, ValueError) as e:
            logger.warning("flags_staff_warm_run_status_present_failed", error=str(e))
            return response.Response({"run": None})

        return response.Response({"run": presented})

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(response=StaffWarmRunCancelResponseSerializer)},
    )
    @action(methods=["POST"], detail=False, url_path="warm_run/cancel")
    def cancel_warm_run(self, request: request.Request, **kwargs) -> response.Response:
        """Request cancellation of the active warm-all run.

        Sets the cancel key the warmer polls between status heartbeats; the run winds down after
        in-flight teams finish. Cancelling a stale run is allowed (the key is scoped to the run id,
        so a dead process simply never reads it).
        """
        cache = _flags_dedicated_cache()
        if cache is None:
            raise ValidationError("The dedicated flags cache (FLAGS_REDIS_URL) is not configured.")

        run = _parse_warm_run_status(cache.get(WARM_RUN_STATUS_CACHE_KEY))
        if run is None or run["state"] != "running":
            raise ValidationError("No warm-all run is currently running.")

        cache.set(WARM_RUN_CANCEL_CACHE_KEY, run["run_id"], WARM_RUN_CANCEL_TTL_SECONDS)

        logger.info(
            "flags_staff_cache_warm_run_cancel",
            staff_user_id=request.user.id,
            was_impersonated=is_impersonated(request),
            run_id=run["run_id"],
        )

        return response.Response(
            {"run_id": run["run_id"], "cancel_requested": True},
            status=status.HTTP_202_ACCEPTED,
        )

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
