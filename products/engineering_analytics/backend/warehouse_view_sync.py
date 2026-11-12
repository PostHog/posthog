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

# Only a load of one of these schemas can change which views a team gets.
_RELEVANT_SCHEMAS: dict[str, tuple[str, ...]] = {
    ExternalDataSourceType.GITHUB: (WORKFLOW_RUNS_SCHEMA, WORKFLOW_JOBS_SCHEMA),
    ExternalDataSourceType.DEPOT: (DEPOT_JOB_ATTEMPTS_SCHEMA,),
}


def sync_engineering_analytics_views(schema: ExternalDataSchema, source: ExternalDataSource) -> None:
    """Runs after a warehouse schema load. Never raises, and never enrolls a team: this product's
    views must not appear in a warehouse until a user enables the product.
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
        # A dropped pooler connection is transient, so it gets no error-tracking issue. The views
        # stay stale until the next relevant load runs this hook again.
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
