from django.db import close_old_connections

import structlog
from temporalio import activity

from products.error_tracking.backend.logic.built_in_filters import refresh_stale_built_in_filter_rules
from products.error_tracking.backend.temporal.built_in_filters_refresh.types import (
    BuiltInFiltersRefreshInputs,
    BuiltInFiltersRefreshResult,
)

logger = structlog.get_logger(__name__)


@activity.defn
def refresh_built_in_filter_rules_activity(inputs: BuiltInFiltersRefreshInputs) -> BuiltInFiltersRefreshResult:
    # Temporal workers are long-lived, so refresh any stale Django DB connection before querying.
    close_old_connections()

    result = refresh_stale_built_in_filter_rules(batch_size=inputs.batch_size, on_progress=activity.heartbeat)
    logger.info(
        "error_tracking.built_in_filters_refresh.complete",
        rules_refreshed=result.rules_refreshed,
        rules_failed=result.rules_failed,
    )
    return BuiltInFiltersRefreshResult(rules_refreshed=result.rules_refreshed, rules_failed=result.rules_failed)
