import datetime

from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from temporalio import activity

from products.error_tracking.backend.models import (
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
    delete_symbol_set_contents_many,
)
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


def _delete_symbol_set_batch(symbol_set_ids: list[str]) -> tuple[int, set[str]]:
    try:
        with transaction.atomic():
            ErrorTrackingStackFrame.objects.filter(symbol_set_id__in=symbol_set_ids, resolved=False).delete()
            ErrorTrackingSymbolSet.objects.filter(id__in=symbol_set_ids).delete()
        return len(symbol_set_ids), set()
    except Exception as exc:
        if len(symbol_set_ids) == 1:
            logger.exception(
                "error_tracking.symbol_set_cleanup.delete_failed",
                symbol_set_id=symbol_set_ids[0],
                error=str(exc),
            )
            return 0, {symbol_set_ids[0]}

        midpoint = len(symbol_set_ids) // 2
        left_deleted, left_failed = _delete_symbol_set_batch(symbol_set_ids[:midpoint])
        right_deleted, right_failed = _delete_symbol_set_batch(symbol_set_ids[midpoint:])
        return left_deleted + right_deleted, left_failed | right_failed


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
    total_db_failed = 0
    total_storage_failed = 0
    failed_ids: set[str] = set()

    while total_processed < inputs.total_per_run:
        remaining = inputs.total_per_run - total_processed
        chunk_size = min(inputs.batch_size, remaining)
        symbol_sets = list(
            ErrorTrackingSymbolSet.objects.filter(query_filter)
            .exclude(id__in=failed_ids)
            .order_by("id")
            .values_list("id", "storage_ptr")[:chunk_size]
        )

        if not symbol_sets:
            break

        symbol_set_ids = [str(symbol_set_id) for symbol_set_id, _ in symbol_sets]
        storage_ptrs_by_id = {str(symbol_set_id): storage_ptr for symbol_set_id, storage_ptr in symbol_sets}

        deleted_count, batch_failed_ids = _delete_symbol_set_batch(symbol_set_ids)
        total_deleted += deleted_count
        total_db_failed += len(batch_failed_ids)
        failed_ids.update(batch_failed_ids)

        deleted_storage_ptrs = [
            storage_ptr
            for symbol_set_id, storage_ptr in storage_ptrs_by_id.items()
            if storage_ptr and symbol_set_id not in batch_failed_ids
        ]
        if deleted_storage_ptrs:
            try:
                failed_storage_ptrs = delete_symbol_set_contents_many(deleted_storage_ptrs)
            except Exception as exc:
                failed_storage_ptrs = deleted_storage_ptrs
                logger.exception(
                    "error_tracking.symbol_set_cleanup.s3_batch_delete_failed",
                    storage_objects_failed=len(failed_storage_ptrs),
                    error=str(exc),
                )
            if failed_storage_ptrs:
                total_storage_failed += len(failed_storage_ptrs)
                logger.warning(
                    "error_tracking.symbol_set_cleanup.s3_delete_failures",
                    storage_objects_failed=len(failed_storage_ptrs),
                )

        total_processed += len(symbol_sets)
        logger.info(
            "error_tracking.symbol_set_cleanup.progress",
            objects_processed=total_processed,
            objects_deleted=total_deleted,
            objects_failed=total_db_failed,
            storage_objects_failed=total_storage_failed,
        )

    if total_db_failed > 0 or total_storage_failed > 0:
        logger.warning(
            "error_tracking.symbol_set_cleanup.failures",
            objects_processed=total_processed,
            objects_failed=total_db_failed,
            storage_objects_failed=total_storage_failed,
        )

    return SymbolSetCleanupResult(
        objects_processed=total_processed,
        objects_deleted=total_deleted,
        objects_failed=total_db_failed,
        storage_objects_failed=total_storage_failed,
    )
