import datetime

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity

from products.error_tracking.backend.models import ErrorTrackingSymbolSet
from products.error_tracking.backend.temporal.symbol_set_cleanup.types import (
    SymbolSetCleanupInputs,
    SymbolSetCleanupResult,
)

logger = structlog.get_logger(__name__)


def _cleanup_filter(inputs: SymbolSetCleanupInputs) -> Q:
    cutoff_date = timezone.now() - datetime.timedelta(days=inputs.days_old)
    query_filter = Q(last_used__isnull=False) & Q(last_used__lt=cutoff_date)
    if inputs.delete_unused:
        query_filter = query_filter | (Q(last_used__isnull=True) & Q(created_at__lt=cutoff_date))
    return query_filter


@activity.defn
def cleanup_symbol_sets_activity(inputs: SymbolSetCleanupInputs) -> SymbolSetCleanupResult:
    """Delete stale symbol sets in bounded batches, preserving model delete behavior."""
    # Temporal workers are long-lived, so refresh any stale Django DB connection before querying.
    close_old_connections()
    query_filter = _cleanup_filter(inputs)

    if inputs.dry_run:
        eligible_count = ErrorTrackingSymbolSet.objects.filter(query_filter).count()
        # Dry runs only log a bounded sample; never log more rows than the real run would process.
        sample_size = min(inputs.batch_size, inputs.total_per_run, eligible_count)
        for symbol_set in ErrorTrackingSymbolSet.objects.filter(query_filter)[:sample_size]:
            logger.info(
                "error_tracking.symbol_set_cleanup.dry_run_candidate",
                symbol_set_id=str(symbol_set.id),
                ref=symbol_set.ref,
                team_id=symbol_set.team_id,
                last_used=symbol_set.last_used.isoformat() if symbol_set.last_used else None,
            )
        logger.info(
            "error_tracking.symbol_set_cleanup.dry_run_complete",
            eligible_count=eligible_count,
            total_per_run=inputs.total_per_run,
        )
        return SymbolSetCleanupResult(
            objects_processed=0,
            objects_deleted=0,
            objects_failed=0,
            eligible_count=eligible_count,
        )

    total_processed = 0
    total_deleted = 0
    total_failed = 0
    failed_ids: set[str] = set()

    while total_processed < inputs.total_per_run:
        remaining = inputs.total_per_run - total_processed
        chunk_size = min(inputs.batch_size, remaining)
        symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(query_filter).exclude(id__in=failed_ids)[:chunk_size])

        if not symbol_sets:
            break

        for symbol_set in symbol_sets:
            try:
                # Calls ErrorTrackingSymbolSet.delete(), which also removes unresolved frames and S3 contents.
                symbol_set.delete()
                total_deleted += 1
            except Exception as exc:
                total_failed += 1
                failed_ids.add(str(symbol_set.id))
                logger.exception(
                    "error_tracking.symbol_set_cleanup.delete_failed",
                    symbol_set_id=str(symbol_set.id),
                    ref=symbol_set.ref,
                    team_id=symbol_set.team_id,
                    error=str(exc),
                )

        total_processed += len(symbol_sets)
        logger.info(
            "error_tracking.symbol_set_cleanup.progress",
            objects_processed=total_processed,
            objects_deleted=total_deleted,
            objects_failed=total_failed,
        )

    if total_failed > 0:
        logger.warning(
            "error_tracking.symbol_set_cleanup.failures",
            objects_processed=total_processed,
            objects_failed=total_failed,
        )

    return SymbolSetCleanupResult(
        objects_processed=total_processed,
        objects_deleted=total_deleted,
        objects_failed=total_failed,
    )
