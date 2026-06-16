from django.core.cache import cache

from rest_framework.throttling import SimpleRateThrottle

from posthog.rate_limit import (
    APIQueriesBurstThrottle,
    APIQueriesSustainedThrottle,
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
)

from products.endpoints.backend.metrics import ENDPOINT_RATE_LIMITED_TOTAL

MATERIALIZED_ENDPOINT_CACHE_KEY = "endpoint_materialized_ready:{team_id}:{endpoint_name}"
MATERIALIZED_ENDPOINT_CACHE_TTL = 3600  # 1 hour fallback TTL


def get_endpoint_materialization_cache_key(team_id: int, endpoint_name: str) -> str:
    return MATERIALIZED_ENDPOINT_CACHE_KEY.format(team_id=team_id, endpoint_name=endpoint_name)


def is_endpoint_materialization_ready(team_id: int, endpoint_name: str) -> bool | None:
    """
    Check if an endpoint's materialization is ready (cached).

    Returns:
        True if materialization is ready
        False if materialization is not ready
        None if cache miss (caller should check DB and populate cache)
    """
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name)
    return cache.get(cache_key)


def set_endpoint_materialization_ready(team_id: int, endpoint_name: str, is_ready: bool) -> None:
    """
    Set the cached materialization ready status for an endpoint.
    Called when:
    - Temporal workflow completes successfully (is_ready=True)
    - Temporal workflow fails (is_ready=False)
    - Materialization is disabled (is_ready=False)
    """
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name)
    cache.set(cache_key, is_ready, timeout=MATERIALIZED_ENDPOINT_CACHE_TTL)


def clear_endpoint_materialization_cache(team_id: int, endpoint_name: str) -> None:
    """Clear the cached materialization status for an endpoint."""
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name)
    cache.delete(cache_key)


def _get_endpoint_info_from_request(request, view) -> tuple[int | None, str | None]:
    """Extract team_id and endpoint_name from request/view context."""
    team_id = getattr(view, "team_id", None)
    endpoint_name = view.kwargs.get("name") if hasattr(view, "kwargs") else None
    return team_id, endpoint_name


def _check_and_cache_materialization_status(team_id: int, endpoint_name: str) -> bool:
    """
    Check materialization status from DB and populate cache.
    Called on cache miss for lazy loading.

    Returns True if endpoint's current version is ready for materialized execution.
    """
    from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
    from products.endpoints.backend.models import Endpoint

    try:
        endpoint = Endpoint.objects.get(team_id=team_id, name=endpoint_name, is_active=True, deleted=False)
        version = endpoint.get_version()

        is_ready = (
            version.is_materialized
            and version.saved_query is not None
            and version.saved_query.status == DataWarehouseSavedQuery.Status.COMPLETED
        )

        set_endpoint_materialization_ready(team_id, endpoint_name, is_ready)
        return is_ready
    except Endpoint.DoesNotExist:
        set_endpoint_materialization_ready(team_id, endpoint_name, False)
        return False


def _is_materialized_endpoint_request(request, view) -> bool:
    """Check if this request is for a materialized endpoint (cached check with lazy loading)."""
    team_id, endpoint_name = _get_endpoint_info_from_request(request, view)
    if not team_id or not endpoint_name:
        return False

    cached_status = is_endpoint_materialization_ready(team_id, endpoint_name)

    if cached_status is None:
        return _check_and_cache_materialization_status(team_id, endpoint_name)

    return cached_status


class _MaterializedRateMixin(SimpleRateThrottle):
    """Swaps in the higher materialized-endpoint rate and records 429s, on top of any base throttle.

    Mix in before a SimpleRateThrottle subclass — `allow_request` adjusts the rate/scope for
    materialized endpoints, then defers to the base throttle's own gating (which sits between
    this mixin and SimpleRateThrottle in the MRO).
    """

    materialized_rate: str
    materialized_scope: str

    def allow_request(self, request, view):
        if _is_materialized_endpoint_request(request, view):
            self.rate = self.materialized_rate
            self.scope = self.materialized_scope
            self.num_requests, self.duration = self.parse_rate(self.rate)

        allowed = super().allow_request(request, view)
        if not allowed:
            try:
                ENDPOINT_RATE_LIMITED_TOTAL.labels(scope=self.scope).inc()
            except Exception:
                pass
        return allowed


class EndpointBurstThrottle(_MaterializedRateMixin, PersonalOrProjectSecretApiKeyRateThrottle, APIQueriesBurstThrottle):
    """
    Adaptive burst throttle for endpoints, keyed per credential (personal API key or PSAK).
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_burst bucket.
    """

    materialized_rate = "1200/minute"
    materialized_scope = "materialized_endpoint_burst"


class EndpointSustainedThrottle(
    _MaterializedRateMixin, PersonalOrProjectSecretApiKeyRateThrottle, APIQueriesSustainedThrottle
):
    """
    Adaptive sustained throttle for endpoints, keyed per credential (personal API key or PSAK).
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_sustained bucket.
    """

    materialized_rate = "12000/hour"
    materialized_scope = "materialized_endpoint_sustained"


class EndpointProjectSecretApiKeyTeamBurstThrottle(_MaterializedRateMixin, ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate burst budget across all of a project's PSAKs — same size as the per-key
    budget, so minting extra keys never multiplies a project's total burst capacity."""

    # Own scope (not api_queries_burst) so 429 metrics and cache keys name the bucket that tripped.
    scope = "endpoint_psak_team_burst"
    rate = APIQueriesBurstThrottle.rate
    materialized_rate = EndpointBurstThrottle.materialized_rate
    materialized_scope = "materialized_endpoint_psak_team_burst"


class EndpointProjectSecretApiKeyTeamSustainedThrottle(_MaterializedRateMixin, ProjectSecretApiKeyTeamRateThrottle):
    """Per-team aggregate sustained budget across all of a project's PSAKs."""

    scope = "endpoint_psak_team_sustained"
    rate = APIQueriesSustainedThrottle.rate
    materialized_rate = EndpointSustainedThrottle.materialized_rate
    materialized_scope = "materialized_endpoint_psak_team_sustained"
