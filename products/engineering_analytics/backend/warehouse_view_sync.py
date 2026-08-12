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

    Returns early unless a GitHub runs/jobs endpoint just loaded. In the steady state the team's
    viewset already exists, so it re-syncs directly (``sync_views`` recomputes the expected views).
    The expected-views guard runs only on first provisioning: a team whose jobs source isn't synced
    yet has no view to expose, so the viewset row isn't created until both endpoints exist.
    """
    try:
        if source.source_type != ExternalDataSourceType.GITHUB or schema.name not in _RELEVANT_SCHEMAS:
            return

        managed_viewset = DataWarehouseManagedViewSet.objects.filter(
            team=schema.team,
            kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS,
        ).first()

        # Only on first provisioning: computing the expected views is the expensive part, so once the
        # viewset exists we skip this guard and re-sync directly (one compute inside sync_views). A
        # team whose jobs source isn't synced yet has no view to expose — don't create the viewset row.
        if managed_viewset is None:
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
