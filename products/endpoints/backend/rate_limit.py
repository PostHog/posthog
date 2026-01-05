from django.core.cache import cache

from posthog.rate_limit import APIQueriesBurstThrottle, APIQueriesSustainedThrottle

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

    Returns True if endpoint is ready for materialized execution.
    """
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery
    from products.endpoints.backend.models import Endpoint

    try:
        endpoint = Endpoint.objects.select_related("saved_query").get(
            team_id=team_id, name=endpoint_name, is_active=True
        )

        is_ready = (
            endpoint.is_materialized
            and endpoint.saved_query is not None
            and endpoint.saved_query.status == DataWarehouseSavedQuery.Status.COMPLETED
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


class EndpointBurstThrottle(APIQueriesBurstThrottle):
    """
    Adaptive burst throttle for endpoints.
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_burst bucket.
    """

    def allow_request(self, request, view):
        if _is_materialized_endpoint_request(request, view):
            self.rate = "1200/minute"
            self.scope = "materialized_endpoint_burst"
            self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)


class EndpointSustainedThrottle(APIQueriesSustainedThrottle):
    """
    Adaptive sustained throttle for endpoints.
    Uses higher rate limit for materialized endpoints.
    Non-materialized endpoints share the api_queries_sustained bucket.
    """

    def allow_request(self, request, view):
        if _is_materialized_endpoint_request(request, view):
            self.rate = "12000/hour"
            self.scope = "materialized_endpoint_sustained"
            self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)
