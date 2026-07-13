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

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.engineering_analytics.backend.facade.warehouse_views import get_expected_warehouse_views
from products.engineering_analytics.backend.logic.sources import WORKFLOW_JOBS_SCHEMA, WORKFLOW_RUNS_SCHEMA
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

logger = structlog.get_logger(__name__)

# The view joins both endpoints, so only a load of one of them can change its contents. Ignore
# every other schema (pull_requests, and non-GitHub sources) so unrelated syncs stay cheap.
_RELEVANT_SCHEMAS = (WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA)


def sync_engineering_analytics_views(schema: ExternalDataSchema, source: ExternalDataSource) -> None:
    """Called after validate_schema_and_update_table links a DataWarehouseTable to the schema.

    Returns early unless a GitHub runs/jobs endpoint just loaded. Builds the expected views first;
    if the team has no source with both endpoints synced there's nothing to expose, so no viewset
    row is created. Otherwise get-or-creates the team's engineering-analytics viewset and syncs.
    """
    try:
        if source.source_type != ExternalDataSourceType.GITHUB or schema.name not in _RELEVANT_SCHEMAS:
            return

        # Build first: a team whose jobs source isn't synced yet has no view to expose, so don't
        # even create the viewset row (keeps sync a no-op until both endpoints exist).
        if not get_expected_warehouse_views(schema.team):
            return

        managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=schema.team,
            kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
        )

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
        # Transient pooler connection drop — the pipeline retries the post-load hook on a fresh
        # connection, so log for visibility but don't spin up an error-tracking issue.
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
