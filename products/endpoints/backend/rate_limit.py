"""Materialized-serving cache for endpoint versions.

Read by the presentation throttles (a request served from a materialized table gets
a higher rate budget). The DRF throttle classes themselves live in
``presentation/throttles.py``.

The cached value is a ``MaterializedServingState`` snapshot, so classifying a request
needs only the snapshot and the request body. The cache is read-through: the database
is read on a miss, and the entry expires with the table's freshness window. Writes that
change the snapshot (materialization enable/disable, freshness edits) clear the entry.
"""

from collections.abc import Iterable
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from pydantic import ValidationError

from posthog.schema import EndpointRefreshMode, EndpointRunRequest

from products.data_modeling.backend.facade.api import saved_query_materialized_at
from products.endpoints.backend.logic.materialized_serving import MaterializedServingState, serving_state_for_version
from products.endpoints.backend.logic.strategies import strategy_for
from products.endpoints.backend.models import Endpoint, EndpointVersion

MATERIALIZED_ENDPOINT_CACHE_KEY = "endpoint_materialized_state:{team_id}:{endpoint_name}:{version_label}"
MATERIALIZED_ENDPOINT_CACHE_TTL = 3600  # 1 hour fallback TTL
# A snapshot that has gone stale is re-read this often, so a refreshed table regains the budget quickly.
STALE_STATE_RECHECK_TTL = 60

CURRENT_VERSION_LABEL = "current"


def _version_label(version: int | None) -> str:
    return f"v{version}" if version is not None else CURRENT_VERSION_LABEL


def get_endpoint_materialization_cache_key(team_id: int, endpoint_name: str, version: int | None = None) -> str:
    return MATERIALIZED_ENDPOINT_CACHE_KEY.format(
        team_id=team_id, endpoint_name=endpoint_name, version_label=_version_label(version)
    )


def get_endpoint_materialization_state(
    team_id: int, endpoint_name: str, version: int | None = None
) -> MaterializedServingState | None:
    """The cached serving snapshot, or None on a cache miss."""
    payload = cache.get(get_endpoint_materialization_cache_key(team_id, endpoint_name, version))
    if not isinstance(payload, dict):
        return None
    return MaterializedServingState.from_cache(payload)


def is_endpoint_materialization_ready(team_id: int, endpoint_name: str, version: int | None = None) -> bool | None:
    """Cached readiness only: True/False, or None on a cache miss."""
    state = get_endpoint_materialization_state(team_id, endpoint_name, version)
    return state.ready if state is not None else None


def _cache_timeout(state: MaterializedServingState, *, pending: bool = False) -> int:
    # The cache only refills on a miss. A snapshot that outlives its freshness window would
    # keep the endpoint on the inline rate after the next run refreshed the table, so the
    # entry expires with the window.
    if not state.ready or state.materialized_at is None or not state.freshness_seconds:
        # A pending materialization becomes servable on its own, with nothing to refill the
        # entry, so hold it only briefly. A version with no materialization keeps the full
        # window, because it becomes servable only through an edit, which clears the entry.
        return STALE_STATE_RECHECK_TTL if pending else MATERIALIZED_ENDPOINT_CACHE_TTL
    remaining = (state.materialized_at + timedelta(seconds=state.freshness_seconds) - timezone.now()).total_seconds()
    return int(max(STALE_STATE_RECHECK_TTL, min(remaining, MATERIALIZED_ENDPOINT_CACHE_TTL)))


def set_endpoint_materialization_state(
    team_id: int,
    endpoint_name: str,
    state: MaterializedServingState,
    version: int | None = None,
    *,
    pending: bool = False,
) -> None:
    """Cache the snapshot. ``pending`` marks a materialization that has yet to produce a table."""
    cache_key = get_endpoint_materialization_cache_key(team_id, endpoint_name, version)
    cache.set(cache_key, state.to_cache(), timeout=_cache_timeout(state, pending=pending))


def set_endpoint_materialization_ready(
    team_id: int, endpoint_name: str, is_ready: bool, version: int | None = None
) -> None:
    """Cache a bare readiness flag with no serving detail.

    A True flag with no materialization time never serves a request, so callers with a
    live version should cache a full snapshot through ``set_endpoint_materialization_state``.
    """
    state = MaterializedServingState(
        ready=is_ready, materialized_at=None, freshness_seconds=None, servable_variables=frozenset()
    )
    set_endpoint_materialization_state(team_id, endpoint_name, state, version)


def clear_endpoint_materialization_cache(
    team_id: int, endpoint_name: str, versions: Iterable[int] | None = None
) -> None:
    """Clear the cached materialization status for the given versions plus the "current" key."""
    keys = [get_endpoint_materialization_cache_key(team_id, endpoint_name)]
    if versions is not None:
        keys.extend(get_endpoint_materialization_cache_key(team_id, endpoint_name, version) for version in versions)
    cache.delete_many(keys)


def _serving_state(endpoint: Endpoint, version: EndpointVersion, is_ready: bool) -> MaterializedServingState:
    saved_query = version.saved_query
    if not is_ready or saved_query is None:
        return MaterializedServingState.not_ready()
    return serving_state_for_version(
        version,
        strategy_for(endpoint, version, endpoint.team),
        ready=True,
        materialized_at=saved_query_materialized_at(saved_query),
    )


def update_materialization_ready_for_saved_query(team_id: int, saved_query, is_ready: bool) -> None:
    """Refresh the cache for the endpoint version backed by this saved query.

    Used by the data modeling workflow on materialization completion/failure. Updates the
    version's own key, and the "current" key when that version is the endpoint's current one.
    """

    # Scope by endpoint__team_id: EndpointVersion.team is a nullable denormalized field.
    version = (
        EndpointVersion.objects.select_related("endpoint", "endpoint__team")
        .filter(saved_query=saved_query, endpoint__team_id=team_id)
        .first()
    )
    if version is None:
        return

    endpoint_name = version.endpoint.name
    state = _serving_state(version.endpoint, version, is_ready)
    set_endpoint_materialization_state(team_id, endpoint_name, state, version=version.version)
    if version.version == version.endpoint.current_version:
        set_endpoint_materialization_state(team_id, endpoint_name, state)


def _load_and_cache_materialization_state(
    team_id: int, endpoint_name: str, version: int | None = None
) -> MaterializedServingState:
    """Read the targeted version (current when version is None) from the DB and cache its snapshot."""

    try:
        endpoint = Endpoint.objects.select_related("team").get(
            team_id=team_id, name=endpoint_name, is_active=True, deleted=False
        )
        endpoint_version = endpoint.get_version(version)
    except (Endpoint.DoesNotExist, EndpointVersion.DoesNotExist):
        state = MaterializedServingState.not_ready()
        set_endpoint_materialization_state(team_id, endpoint_name, state, version=version)
        return state

    saved_query = endpoint_version.saved_query
    if not endpoint_version.is_materialized or saved_query is None or saved_query.table_id is None:
        state = MaterializedServingState.not_ready()
    else:
        # Same test the execution service applies: a live table plus a completed run. A
        # failed run after a good one leaves the last table servable, so the newest
        # job's status is not the readiness signal.
        materialized_at = saved_query_materialized_at(saved_query)
        state = serving_state_for_version(
            endpoint_version,
            strategy_for(endpoint, endpoint_version, endpoint.team),
            ready=materialized_at is not None,
            materialized_at=materialized_at,
        )
    # A backing saved query means materialization is enabled, so a first table can land at any
    # moment without a request or an edit to refill this entry.
    pending = not state.ready and endpoint_version.saved_query_id is not None
    set_endpoint_materialization_state(team_id, endpoint_name, state, version=version, pending=pending)
    return state


def _check_and_cache_materialization_status(team_id: int, endpoint_name: str, version: int | None = None) -> bool:
    return _load_and_cache_materialization_state(team_id, endpoint_name, version).ready


def check_materialization_ready(team_id: int, endpoint_name: str, version: int | None = None) -> bool:
    """Cached readiness check with a DB fallback on cache miss."""
    cached_status = is_endpoint_materialization_ready(team_id, endpoint_name, version)
    if cached_status is None:
        return _check_and_cache_materialization_status(team_id, endpoint_name, version)
    return cached_status


def check_materialized_request(team_id: int, endpoint_name: str, version: int | None, request_data: object) -> bool:
    """Whether this run request will be served from the targeted version's materialized table.

    The cached snapshot answers "what can this version serve"; the request decides whether
    it will (``refresh=direct``, variables the table cannot filter on, or a stale
    materialization all run inline). A body the run action would reject is classified
    inline, because throttling runs before validation.
    """

    try:
        data = EndpointRunRequest.model_validate(request_data)
    except ValidationError:
        return False
    if data.refresh == EndpointRefreshMode.DIRECT:
        return False

    state = get_endpoint_materialization_state(team_id, endpoint_name, version)
    if state is None:
        state = _load_and_cache_materialization_state(team_id, endpoint_name, version)
    return state.serves(data)
