from collections.abc import Iterable

from django.core.cache import cache

from rest_framework.throttling import SimpleRateThrottle

from posthog.rate_limit import (
    APIQueriesBurstThrottle,
    APIQueriesSustainedThrottle,
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
)

from products.endpoints.backend.metrics import ENDPOINT_RATE_LIMITED_TOTAL

# Keyed per version so the throttle budget matches the version actually being executed:
# an explicit `?version=N` request is classified by that version's readiness, everything
# else by the current version's (the "current" label).
MATERIALIZED_ENDPOINT_CACHE_KEY = "endpoint_materialized_ready:{team_id}:{endpoint_name}:{version_label}"
MATERIALIZED_ENDPOINT_CACHE_TTL = 3600  # 1 hour fallback TTL

CURRENT_VERSION_LABEL = "current"


def _version_label(version: int | None) -> str:
    return f"v{version}" if version is not None else CURRENT_VERSION_LABEL


def get_endpoint_materialization_cache_key(team_id: int, endpoint_name: str, version: int | None = None) -> str:
    return MATERIALIZED_ENDPOINT_CACHE_KEY.format(
        team_id=team_id, endpoint_name=endpoint_name, version_label=_version_label(version)
    )


def is_endpoint_materialization_ready(team_id: int, endpoint_name: str, version: int | None = None) -> bool | None:
    """
    Check if an endpoint version's materialization is ready (cached).

    Returns:
        True if materialization is ready
        False if materialization is not ready
        None if cache miss (caller should check DB and populate cache)
    """
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name, version)
    return cache.get(cache_key)


def set_endpoint_materialization_ready(
    team_id: int, endpoint_name: str, is_ready: bool, version: int | None = None
) -> None:
    """
    Set the cached materialization ready status for an endpoint version.
    Called when:
    - Temporal workflow completes successfully (is_ready=True)
    - Temporal workflow fails (is_ready=False)
    - Materialization is disabled (is_ready=False)
    """
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name, version)
    cache.set(cache_key, is_ready, timeout=MATERIALIZED_ENDPOINT_CACHE_TTL)


def clear_endpoint_materialization_cache(
    team_id: int, endpoint_name: str, versions: Iterable[int] | None = None
) -> None:
    """Clear the cached materialization status for the given versions plus the "current" key."""
    keys = [get_endpoint_materialization_cache_key(team_id, endpoint_name)]
    if versions is not None:
        keys.extend(get_endpoint_materialization_cache_key(team_id, endpoint_name, version) for version in versions)
    cache.delete_many(keys)


def update_materialization_ready_for_saved_query(team_id: int, saved_query, is_ready: bool) -> None:
    """Update the readiness cache for the endpoint version backed by this saved query.

    Used by the data modeling workflow on materialization completion/failure. Updates the
    version's own key, and the "current" key when that version is the endpoint's current one.
    """
    from products.endpoints.backend.models import EndpointVersion

    # Scope by endpoint__team_id: EndpointVersion.team is a nullable denormalized field.
    version = (
        EndpointVersion.objects.select_related("endpoint")
        .filter(saved_query=saved_query, endpoint__team_id=team_id)
        .first()
    )
    if version is None:
        return

    endpoint_name = version.endpoint.name
    set_endpoint_materialization_ready(team_id, endpoint_name, is_ready, version=version.version)
    if version.version == version.endpoint.current_version:
        set_endpoint_materialization_ready(team_id, endpoint_name, is_ready)


def _parse_requested_version(request) -> int | None:
    """Best-effort parse of the targeted version from the request (body first, then query params).

    Mirrors EndpointViewSet._parse_version_param; invalid or absent values fall back to None
    (current version) — the view validates and rejects properly later.
    """
    try:
        body_version = request.data.get("version") if hasattr(request, "data") else None
        raw_version = body_version if body_version is not None else request.query_params.get("version")
        return int(raw_version) if raw_version is not None else None
    except Exception:
        return None


def _get_endpoint_info_from_request(request, view) -> tuple[int | None, str | None, int | None]:
    """Extract team_id, endpoint_name, and requested version from request/view context."""
    team_id = getattr(view, "team_id", None)
    endpoint_name = view.kwargs.get("name") if hasattr(view, "kwargs") else None
    return team_id, endpoint_name, _parse_requested_version(request)


def _check_and_cache_materialization_status(team_id: int, endpoint_name: str, version: int | None = None) -> bool:
    """
    Check materialization status from DB and populate cache.
    Called on cache miss for lazy loading.

    Returns True if the targeted endpoint version (current when version is None) is ready
    for materialized execution.
    """
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
    from products.endpoints.backend.models import Endpoint, EndpointVersion

    try:
        endpoint = Endpoint.objects.get(team_id=team_id, name=endpoint_name, is_active=True, deleted=False)
        endpoint_version = endpoint.get_version(version)

        is_ready = (
            endpoint_version.is_materialized
            and endpoint_version.saved_query is not None
            and endpoint_version.saved_query.status == DataWarehouseSavedQuery.Status.COMPLETED
        )

        set_endpoint_materialization_ready(team_id, endpoint_name, is_ready, version=version)
        return is_ready
    except (Endpoint.DoesNotExist, EndpointVersion.DoesNotExist):
        set_endpoint_materialization_ready(team_id, endpoint_name, False, version=version)
        return False


def _is_materialized_endpoint_request(request, view) -> bool:
    """Check if this request targets a materialized endpoint version (cached check with lazy loading)."""
    team_id, endpoint_name, version = _get_endpoint_info_from_request(request, view)
    if not team_id or not endpoint_name:
        return False

    cached_status = is_endpoint_materialization_ready(team_id, endpoint_name, version)

    if cached_status is None:
        return _check_and_cache_materialization_status(team_id, endpoint_name, version)

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
