"""Re-sync the engineering-analytics per-job CI cost view after a warehouse data load completes.

Registered into the data-import pipeline via warehouse_sources' external_product_hooks at
app-ready (see apps.py), so the pipeline can trigger it without importing this product
(engineering_analytics depends on warehouse_sources, not the other way round).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import InterfaceError, OperationalError

import structlog

from posthog.exceptions_capture import capture_exception

from products.engineering_analytics.backend.logic.enrollment import get_enrollment
from products.engineering_analytics.backend.logic.sources import (
    DEPOT_JOB_ATTEMPTS_SCHEMA,
    WORKFLOW_JOBS_SCHEMA,
    WORKFLOW_RUNS_SCHEMA,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

logger = structlog.get_logger(__name__)

# The view joins both endpoints and the Depot CI attempts, so only a load of one of them can change
# its contents. Ignore every other schema so unrelated syncs stay cheap.
_RELEVANT_SCHEMAS: dict[str, tuple[str, ...]] = {
    ExternalDataSourceType.GITHUB: (WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA),
    ExternalDataSourceType.DEPOT: (DEPOT_JOB_ATTEMPTS_SCHEMA,),
}


def sync_engineering_analytics_views(schema: ExternalDataSchema, source: ExternalDataSource) -> None:
    """Called after validate_schema_and_update_table links a DataWarehouseTable to the schema.

    Returns early unless a GitHub runs/jobs or Depot attempts endpoint just loaded, and only
    re-syncs a team that opted in (``sync_views`` recomputes the expected views). The opt-in row
    is never created here: a team connects a GitHub source for many reasons, and this product's
    views must not appear in its warehouse until a user enables the product.
    """
    try:
        if schema.name not in _RELEVANT_SCHEMAS.get(source.source_type, ()):
            return

        managed_viewset = get_enrollment(schema.team)
        if managed_viewset is None:
            logger.info(
                "sync_engineering_analytics_views_skipped_not_enrolled",
                team_id=schema.team_id,
                source_id=str(source.id),
            )
            return

        logger.info(
            "sync_engineering_analytics_views_starting",
            team_id=schema.team_id,
            source_id=str(source.id),
            schema_name=schema.name,
        )
        managed_viewset.sync_views()
        logger.info(
            "sync_engineering_analytics_views_completed",
            team_id=schema.team_id,
            source_id=str(source.id),
        )
    except (OperationalError, InterfaceError) as e:
        # Transient pooler connection drop — swallowed, so the view stays stale until the next
        # runs/jobs load re-runs this hook on a fresh connection. Log for visibility but don't
        # spin up an error-tracking issue for a momentary pooler blip.
        logger.warning(
            "sync_engineering_analytics_views_transient_db_error",
            team_id=schema.team_id,
            source_id=str(source.id),
            error=str(e),
        )
    except Exception as e:
        logger.exception(
            "sync_engineering_analytics_views_failed",
            team_id=schema.team_id,
            source_id=str(source.id),
            error=str(e),
        )
        capture_exception(e)
