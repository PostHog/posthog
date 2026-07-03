"""Materialization-readiness cache for endpoint versions.

Read by the presentation throttles (materialized endpoints get a higher rate
budget) and written by the data-modeling Temporal workflow on materialization
completion/failure. The DRF throttle classes themselves live in
``presentation/throttles.py``.
"""

from collections.abc import Iterable

from django.core.cache import cache

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


def check_materialization_ready(team_id: int, endpoint_name: str, version: int | None = None) -> bool:
    """Cached readiness check with a DB fallback on cache miss."""
    cached_status = is_endpoint_materialization_ready(team_id, endpoint_name, version)
    if cached_status is None:
        return _check_and_cache_materialization_status(team_id, endpoint_name, version)
    return cached_status
