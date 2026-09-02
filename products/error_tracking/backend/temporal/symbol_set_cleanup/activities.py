import time
import datetime
from itertools import batched
from uuid import UUID

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, close_old_connections, models, transaction
from django.db.models import F, Q
from django.db.models.lookups import GreaterThan
from django.utils import timezone

import structlog
from temporalio import activity

from products.error_tracking.backend.models import (
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
    delete_symbol_set_contents_many,
    symbol_set_cleanup_bucket_expression,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup.types import (
    SYMBOL_SET_CLEANUP_BUCKET_COUNT,
    SymbolSetCleanupInputs,
    SymbolSetCleanupResult,
)

logger = structlog.get_logger(__name__)

_DELETE_REQUEST_BATCH_SIZE = 1000
_DELETE_REQUEST_PACING_SECONDS = 0.1


def _cleanup_read_database() -> str:
    return "replica" if "replica" in settings.DATABASES else DEFAULT_DB_ALIAS


def _cleanup_branches(inputs: SymbolSetCleanupInputs) -> list[Q]:
    cutoff_date = timezone.now() - datetime.timedelta(days=inputs.days_old)
    query_branches = [Q(last_used__isnull=False, last_used__lt=cutoff_date)]
    if inputs.delete_unused:
        query_branches.append(Q(last_used__isnull=True, created_at__lt=cutoff_date))
    return query_branches


def _row(*expressions: F | models.Expression) -> models.Func:
    return models.Func(*expressions, function="", template="(%(expressions)s)", output_field=models.Field())


def _after_cursor(cursor: tuple[datetime.datetime | None, datetime.datetime, UUID]) -> GreaterThan:
    last_used, created_at, symbol_set_id = cursor
    if last_used is None:
        return GreaterThan(
            _row(F("created_at"), F("id")),
            _row(models.Value(created_at), models.Value(symbol_set_id)),
        )
    return GreaterThan(
        _row(F("last_used"), F("created_at"), F("id")),
        _row(models.Value(last_used), models.Value(created_at), models.Value(symbol_set_id)),
    )


def _bucket_queryset(*, query_filter: Q, bucket: int) -> models.QuerySet[ErrorTrackingSymbolSet]:
    return (
        ErrorTrackingSymbolSet.objects.using(_cleanup_read_database())
        .alias(cleanup_bucket=symbol_set_cleanup_bucket_expression())
        .filter(query_filter, cleanup_bucket=bucket)
        .order_by(
            "cleanup_bucket",
            F("last_used").asc(nulls_last=True),
            "created_at",
            "id",
        )
    )


def _cleanup_queryset(
    *,
    query_filter: Q,
    bucket: int,
    cursor: tuple[datetime.datetime | None, datetime.datetime, UUID] | None,
) -> models.QuerySet[ErrorTrackingSymbolSet]:
    queryset = _bucket_queryset(query_filter=query_filter, bucket=bucket)
    if cursor is not None:
        queryset = queryset.filter(_after_cursor(cursor))
    return queryset


def _assigned_buckets(inputs: SymbolSetCleanupInputs) -> list[int]:
    worker_count = max(1, min(inputs.bucket_worker_count, SYMBOL_SET_CLEANUP_BUCKET_COUNT))
    worker_index = inputs.bucket_worker_index % worker_count
    return [
        (inputs.bucket_offset + bucket) % SYMBOL_SET_CLEANUP_BUCKET_COUNT
        for bucket in range(worker_index, SYMBOL_SET_CLEANUP_BUCKET_COUNT, worker_count)
    ]


def _delete_symbol_set_batch(symbol_set_ids: list[str]) -> tuple[int, set[str]]:
    try:
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            ErrorTrackingStackFrame.objects.using(DEFAULT_DB_ALIAS).filter(
                symbol_set_id__in=symbol_set_ids, resolved=False
            ).delete()
            ErrorTrackingSymbolSet.objects.using(DEFAULT_DB_ALIAS).filter(id__in=symbol_set_ids).delete()
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


def _delete_symbol_set_contents_with_pacing(storage_ptrs: list[str]) -> list[str]:
    failed_storage_ptrs: list[str] = []
    for batch_number, storage_ptr_batch in enumerate(batched(storage_ptrs, _DELETE_REQUEST_BATCH_SIZE, strict=False)):
        if batch_number > 0:
            time.sleep(_DELETE_REQUEST_PACING_SECONDS)
        failed_storage_ptrs.extend(delete_symbol_set_contents_many(list(storage_ptr_batch)))
    return failed_storage_ptrs


@activity.defn
def cleanup_symbol_sets_activity(inputs: SymbolSetCleanupInputs) -> SymbolSetCleanupResult:
    """Delete stale symbol sets in bounded batches, preserving model delete behavior."""
    # Temporal workers are long-lived, so refresh any stale Django DB connection before querying.
    close_old_connections()
    cleanup_branches = _cleanup_branches(inputs)

    if inputs.dry_run:
        buckets = _assigned_buckets(inputs)
        branch_querysets = [
            _bucket_queryset(query_filter=query_filter, bucket=bucket)
            for bucket in buckets
            for query_filter in cleanup_branches
        ]
        eligible_count = sum(queryset.count() for queryset in branch_querysets)
        # Dry runs only log a bounded sample; never log more rows than the real run would process.
        sample_size = min(inputs.batch_size, inputs.total_per_run, eligible_count)
        candidates: list[ErrorTrackingSymbolSet] = []
        for queryset in branch_querysets:
            candidates.extend(queryset[: sample_size - len(candidates)])
            if len(candidates) == sample_size:
                break
        for symbol_set in candidates:
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

    for bucket in _assigned_buckets(inputs):
        for query_filter in cleanup_branches:
            cursor: tuple[datetime.datetime | None, datetime.datetime, UUID] | None = None
            while total_processed < inputs.total_per_run:
                remaining = inputs.total_per_run - total_processed
                chunk_size = min(inputs.batch_size, remaining)
                queryset = _cleanup_queryset(
                    query_filter=query_filter,
                    bucket=bucket,
                    cursor=cursor,
                )
                symbol_sets = list(queryset.values_list("id", "storage_ptr", "last_used", "created_at")[:chunk_size])

                if not symbol_sets:
                    break

                cursor = (symbol_sets[-1][2], symbol_sets[-1][3], symbol_sets[-1][0])
                symbol_set_ids = [str(symbol_set_id) for symbol_set_id, _, _, _ in symbol_sets]
                storage_ptrs_by_id = {
                    str(symbol_set_id): storage_ptr for symbol_set_id, storage_ptr, _, _ in symbol_sets
                }
                deleted_count, batch_failed_ids = _delete_symbol_set_batch(symbol_set_ids)

                total_deleted += deleted_count
                total_db_failed += len(batch_failed_ids)

                deleted_storage_ptrs = [
                    storage_ptr
                    for symbol_set_id, storage_ptr in storage_ptrs_by_id.items()
                    if storage_ptr and symbol_set_id not in batch_failed_ids
                ]
                if deleted_storage_ptrs:
                    try:
                        failed_storage_ptrs = _delete_symbol_set_contents_with_pacing(deleted_storage_ptrs)
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
                    cleanup_bucket=bucket,
                    objects_processed=total_processed,
                    objects_deleted=total_deleted,
                    objects_failed=total_db_failed,
                    storage_objects_failed=total_storage_failed,
                )

                if len(symbol_sets) < chunk_size:
                    break

            if total_processed >= inputs.total_per_run:
                break
        if total_processed >= inputs.total_per_run:
            break

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
