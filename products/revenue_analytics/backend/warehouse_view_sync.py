"""Re-sync revenue analytics managed views after a warehouse data load completes.

Registered into the data-import pipeline via warehouse_sources' external_product_hooks at
app-ready (see apps.py), so the pipeline can trigger it without importing this product
(revenue_analytics depends on warehouse_sources).
"""

from django.db import InterfaceError, OperationalError

import structlog

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.revenue_analytics.backend.views.orchestrator import SUPPORTED_SOURCES
from products.warehouse_sources.backend.facade.api import list_revenue_source_settings
from products.warehouse_sources.backend.facade.hooks import RevenueViewSyncInput
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

logger = structlog.get_logger(__name__)


def sync_revenue_analytics_views(sync_input: RevenueViewSyncInput) -> None:
    """Called after validate_schema_and_update_table links a DataWarehouseTable to the
    schema, so builders can now produce real queries instead of empty placeholders.
    """
    try:
        if sync_input.source_type not in SUPPORTED_SOURCES:
            return

        sources = list_revenue_source_settings(
            sync_input.team_id,
            include_deleted=True,
            source_types=[sync_input.source_type],
            source_ids=[sync_input.source_id],
        )
        if not sources or (not sources[0].deleted and not sources[0].enabled):
            return

        managed_viewset = DataWarehouseManagedViewSet.objects.filter(
            team_id=sync_input.team_id,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        ).first()

        if managed_viewset is None:
            logger.warning(
                "sync_revenue_analytics_views_skipped_no_viewset",
                team_id=sync_input.team_id,
                source_id=str(sync_input.source_id),
            )
            return

        logger.info(
            "sync_revenue_analytics_views_starting",
            team_id=sync_input.team_id,
            source_id=str(sync_input.source_id),
            schema_name=sync_input.schema_name,
        )
        managed_viewset.sync_views()
        logger.info(
            "sync_revenue_analytics_views_completed",
            team_id=sync_input.team_id,
            source_id=str(sync_input.source_id),
        )
    except (OperationalError, InterfaceError) as e:
        # Transient DB connection drop (the pgbouncer pooler recycling / closing a stale
        # connection mid-query). This isn't a real failure of the view sync: the data-import
        # pipeline retries the post-load hook on a fresh connection. Log for visibility but
        # don't capture_exception — a momentary pooler blip shouldn't spin up an error
        # tracking issue.
        logger.warning(
            "sync_revenue_analytics_views_transient_db_error",
            team_id=sync_input.team_id,
            source_id=str(sync_input.source_id),
            error=str(e),
        )
    except Exception as e:
        logger.exception(
            "sync_revenue_analytics_views_failed",
            team_id=sync_input.team_id,
            source_id=str(sync_input.source_id),
            error=str(e),
        )
        capture_exception(e)
