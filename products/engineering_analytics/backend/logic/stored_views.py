"""When the stored CI views rebuild, and when a read may take their tables.

A rebuild costs the same whether or not anyone reads its table. So a rebuild starts only while a
person or an agent uses the product: the first request after an idle period starts one, and each
data load starts the next one for as long as the requests continue. An idle product starts none.

The managed-view schedule of data_modeling also rebuilds each view, whether or not the product is in use.

A read takes a table only while the table is recent. Any other read takes the raw tables, so a view
that stopped rebuilding makes the product slower, never out of date.
"""

from collections.abc import Collection
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.db.models import Max, QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.data_modeling.backend.facade import api as data_modeling
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.engineering_analytics.backend.facade.contracts import STORED_READS_FEATURE_FLAG
from products.engineering_analytics.backend.logic.feature_flags import team_flag
from products.engineering_analytics.backend.logic.views import ci_jobs, ci_runs
from products.engineering_analytics.backend.logic.views.stored_view import identity_columns, lowest_stored_date
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

STORED_VIEWS = (ci_runs, ci_jobs)

_WINDOWS = {view.VIEW_NAME: view.WINDOW for view in STORED_VIEWS}

_IN_USE_SECONDS = 60 * 60
_MIN_REBUILD_GAP_SECONDS = 10 * 60

# Each load starts a rebuild. Sized for a source that loads every 15 minutes: a table older than this
# missed more than one load, so a read takes the raw tables until a rebuild lands again.
_MAX_TABLE_AGE = timedelta(minutes=45)

# A table built from the view of an earlier load has no row for a raw table that landed after it. A
# rebuild that started before the raw table landed can still finish after it, so a table answers for a
# raw table only when it was built this long after the raw table landed.
_MIN_BUILD_AFTER_RAW_TABLE = timedelta(minutes=30)


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


@frozen
class StoredTables:
    """The tables of the stored CI views that a read may take. ``built_at`` is the build time of the
    table that was built first."""

    built_at: datetime

    def answers(self, view_name: str, floor: str) -> bool:
        """True when the table of the view holds every row at or above the date-only scan ``floor``."""
        return floor >= lowest_stored_date(self.built_at, _WINDOWS[view_name])


def stored_tables_for(
    team: Team, user: "User | None", *, source_id: str, repository: str, raw_tables: Collection[str]
) -> StoredTables | None:
    """The tables that a read of one repository of one source may take. None sends the read to the
    raw tables.

    ``raw_tables`` are the warehouse tables that the stored rows of that repository are built from.
    """
    distinct_id = user.distinct_id if user else None
    if not team_flag(STORED_READS_FEATURE_FLAG, team, distinct_id=distinct_id, only_evaluate_locally=True):
        return None
    views = list(managed_views(team.pk, list(_WINDOWS)).filter(is_materialized=True))
    if len(views) != len(_WINDOWS):
        return None
    # A view takes a source when the first load of the source lands. Before that, its table has no row
    # for the source, and a read cannot tell that from a repository with no CI.
    identity = identity_columns(source_id, repository)
    if any(identity not in ((view.query or {}).get("query") or "") for view in views):
        return None
    builds = [built for view in views if (built := data_modeling.saved_query_materialized_at(view)) is not None]
    if len(builds) != len(views):
        return None
    built_at = min(builds)
    if timezone.now() - built_at > _MAX_TABLE_AGE:
        return None
    newest_raw_table = (
        DataWarehouseTable.objects.filter(team_id=team.pk, name__in=raw_tables)
        .exclude(deleted=True)
        .aggregate(newest=Max("created_at"))["newest"]
    )
    if newest_raw_table is None or built_at < newest_raw_table + _MIN_BUILD_AFTER_RAW_TABLE:
        return None
    return StoredTables(built_at=built_at)
