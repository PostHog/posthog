"""When the stored CI views rebuild.

A rebuild costs the same whether or not anyone reads its table. So the tables rebuild only while a
person or an agent reads the product, and the cost follows the use: the first read after an idle
period starts a rebuild, and each data load starts the next one for as long as the reads continue.
"""

from django.core.cache import cache

import structlog

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade import api as data_modeling
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.engineering_analytics.backend.logic.views import ci_jobs, ci_runs
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

logger = structlog.get_logger(__name__)

# The friction view is materialized too, but it keeps the managed-view schedule, because its replay is
# too heavy to run after every load.
STORED_VIEW_NAMES = (ci_runs.VIEW_NAME, ci_jobs.VIEW_NAME)

# Long enough to span the gaps inside one working session, so the tables stay fresh between page views.
_IN_USE_SECONDS = 60 * 60


def _in_use_key(team_id: int) -> str:
    return f"engineering_analytics:in_use:{team_id}"


def stored_views(team_id: int) -> list[DataWarehouseSavedQuery]:
    """The team's stored views that have a table."""
    return list(
        DataWarehouseSavedQuery.objects.filter(
            team_id=team_id,
            name__in=STORED_VIEW_NAMES,
            # Only this product's managed views count: a user's own saved query can carry the same name.
            managed_viewset__kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
            is_materialized=True,
        ).exclude(deleted=True)
    )


def mark_in_use(team_id: int) -> None:
    """Record a read by a person or an agent. No load rebuilt the tables while nobody read them, so
    the first read after an idle period starts a rebuild. A failure here must not fail the read."""
    key = _in_use_key(team_id)
    try:
        was_idle = cache.add(key, True, timeout=_IN_USE_SECONDS)
        if not was_idle:
            cache.touch(key, timeout=_IN_USE_SECONDS)
    except Exception:
        logger.warning("engineering_analytics_in_use_mark_failed", team_id=team_id, exc_info=True)
        return
    if was_idle:
        _start_rebuild(team_id)


def is_in_use(team_id: int) -> bool:
    """False when the cache gives no answer: a skipped rebuild only delays the tables, and a read
    of a table that is too old takes the raw tables instead."""
    try:
        return bool(cache.get(_in_use_key(team_id)))
    except Exception:
        logger.warning("engineering_analytics_in_use_read_failed", team_id=team_id, exc_info=True)
        return False


def rebuild_after_load(team_id: int) -> None:
    """Start a rebuild of each stored view while the product is in use, so its table trails the load
    that just landed by one rebuild."""
    if is_in_use(team_id):
        _start_rebuild(team_id)


def _start_rebuild(team_id: int) -> None:
    """A rebuild that is already running absorbs the request, so a load that lands during it is picked
    up by the rebuild that the next load starts. A failure is reported, never raised."""
    try:
        views = stored_views(team_id)
    except Exception as e:
        _report_rebuild_failure(e, team_id=team_id, view_name=None)
        return
    for saved_query in views:
        try:
            # Nobody asked for this run, so it must not clear the suspension of a view that keeps failing.
            data_modeling.materialize_saved_query(saved_query, resume=False)
        except Exception as e:
            _report_rebuild_failure(e, team_id=team_id, view_name=saved_query.name)


def _report_rebuild_failure(error: Exception, *, team_id: int, view_name: str | None) -> None:
    logger.exception(
        "rebuild_engineering_analytics_view_failed", team_id=team_id, view_name=view_name, error=str(error)
    )
    capture_exception(error)
