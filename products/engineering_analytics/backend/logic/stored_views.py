"""When the stored CI views rebuild.

A rebuild costs the same whether or not anyone reads its table. So a rebuild starts only while a
person or an agent uses the product: the first request after an idle period starts one, and each
data load starts the next one for as long as the requests continue. An idle product starts none.

The managed-view schedule of data_modeling also rebuilds each view, whether or not the product is in use.
"""

from collections.abc import Collection

from django.core.cache import cache
from django.db.models import QuerySet

import structlog

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade import api as data_modeling
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.engineering_analytics.backend.logic.views import ci_jobs, ci_runs
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

logger = structlog.get_logger(__name__)

# The friction view is materialized too, but it keeps the managed-view schedule, because its replay is
# too heavy to run after every load.
STORED_VIEWS = (ci_runs, ci_jobs)

# Long enough to span the gaps inside one working session, so the tables stay recent between page views.
_IN_USE_SECONDS = 60 * 60

# A view starts at most one rebuild in this time, however many loads and repositories feed it.
_MIN_REBUILD_GAP_SECONDS = 10 * 60


def _in_use_key(team_id: int) -> str:
    return f"engineering_analytics:in_use:{team_id}"


def _rebuild_started_key(team_id: int, view_name: str) -> str:
    return f"engineering_analytics:rebuild_started:{team_id}:{view_name}"


def managed_views(team_id: int, names: Collection[str]) -> QuerySet[DataWarehouseSavedQuery]:
    """The team's managed views of this product that carry one of ``names``. A user's own saved query
    can carry the same name, and it does not count."""
    return DataWarehouseSavedQuery.objects.filter(
        team_id=team_id,
        name__in=names,
        managed_viewset__kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
    ).exclude(deleted=True)


def mark_in_use(team_id: int) -> bool:
    """Record a request by a person or an agent. True when the product was idle before it: no load
    rebuilt the views in that time, so the caller starts a rebuild. A cache that fails reads as not
    idle, because it must not fail the request."""
    key = _in_use_key(team_id)
    try:
        # The key is there for all but the first request of a session, so most requests cost one call.
        if cache.touch(key, timeout=_IN_USE_SECONDS):
            return False
        return cache.add(key, True, timeout=_IN_USE_SECONDS)
    except Exception:
        logger.warning("engineering_analytics_in_use_mark_failed", team_id=team_id, exc_info=True)
        return False


def is_in_use(team_id: int) -> bool:
    """False when the cache gives no answer, because a skipped rebuild only delays the tables."""
    try:
        return bool(cache.get(_in_use_key(team_id)))
    except Exception:
        logger.warning("engineering_analytics_in_use_read_failed", team_id=team_id, exc_info=True)
        return False


def rebuild_after_load(team_id: int, schema_name: str) -> None:
    """Start a rebuild of the views that the load of ``schema_name`` made out of date, while the
    product is in use."""
    if is_in_use(team_id):
        _start_rebuilds(team_id, [view.VIEW_NAME for view in STORED_VIEWS if schema_name in view.REBUILT_AFTER])


def rebuild_all(team_id: int) -> None:
    """Start a rebuild of every stored CI view."""
    _start_rebuilds(team_id, [view.VIEW_NAME for view in STORED_VIEWS])


def _start_rebuilds(team_id: int, view_names: Collection[str]) -> None:
    """A start during a running rebuild does nothing, so the rebuild that the next load starts reads
    that load. A view that cannot start logs the error, and the other views still start."""
    for saved_query in managed_views(team_id, view_names).filter(is_materialized=True):
        if not cache.add(_rebuild_started_key(team_id, saved_query.name), True, timeout=_MIN_REBUILD_GAP_SECONDS):
            continue
        # A suspended view failed its recent rebuilds. A start with ``resume=False`` keeps the suspension
        # but still runs, so without this check every load would run the failing rebuild again.
        if data_modeling.suspension_state_for_saved_query(saved_query):
            continue
        try:
            data_modeling.materialize_saved_query(saved_query, resume=False)
        except Exception as e:
            logger.exception("rebuild_engineering_analytics_view_failed", team_id=team_id, view_name=saved_query.name)
            capture_exception(e)
