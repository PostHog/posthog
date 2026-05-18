import datetime

from django.db.models import Q
from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners

from products.error_tracking.backend.models import ErrorTrackingSymbolSet


class SymbolSetCleanupConfig(dagster.Config):
    days_old: int = 30
    delete_unused: bool = True
    total_per_run: int = 50000
    batch_size: int = 2000
    dry_run: bool = False


@dagster.asset
def symbol_set_cleanup(
    context: dagster.AssetExecutionContext,
    config: SymbolSetCleanupConfig,
) -> dagster.MaterializeResult:
    """
    Delete symbol sets older than the cutoff date in small chunks.
    Each delete() also removes the underlying S3 object, so the loop is I/O bound.
    """
    cutoff_date = timezone.now() - datetime.timedelta(days=config.days_old)

    query_filter = Q(last_used__isnull=False) & Q(last_used__lt=cutoff_date)
    if config.delete_unused:
        query_filter = query_filter | (Q(last_used__isnull=True) & Q(created_at__lt=cutoff_date))

    if config.dry_run:
        eligible_count = ErrorTrackingSymbolSet.objects.filter(query_filter).count()
        sample_size = min(config.batch_size, config.total_per_run, eligible_count)
        for symbol_set in ErrorTrackingSymbolSet.objects.filter(query_filter)[:sample_size]:
            last_used_str = symbol_set.last_used.isoformat() if symbol_set.last_used else "never"
            context.log.info(
                f"DRY RUN: Would delete symbol set {symbol_set.id} "
                f"(ref: {symbol_set.ref}, team: {symbol_set.team_id}, "
                f"last_used: {last_used_str})"
            )
        context.log.info(
            f"DRY RUN: {eligible_count} symbol set(s) eligible for deletion "
            f"(would process up to {config.total_per_run} per run)"
        )
        return dagster.MaterializeResult(
            metadata={
                "objects_processed": dagster.MetadataValue.int(0),
                "objects_deleted": dagster.MetadataValue.int(0),
                "objects_failed": dagster.MetadataValue.int(0),
                "eligible_count": dagster.MetadataValue.int(eligible_count),
                "dry_run": dagster.MetadataValue.bool(True),
            }
        )

    total_processed = 0
    total_deleted = 0
    total_failed = 0
    failed_ids: set[int] = set()

    while total_processed < config.total_per_run:
        remaining = config.total_per_run - total_processed
        chunk_size = min(config.batch_size, remaining)
        symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(query_filter).exclude(id__in=failed_ids)[:chunk_size])

        if not symbol_sets:
            break

        for symbol_set in symbol_sets:
            try:
                symbol_set.delete()
                total_deleted += 1
            except Exception as e:
                total_failed += 1
                failed_ids.add(symbol_set.id)
                context.log.exception(
                    f"Failed to delete symbol set {symbol_set.id} "
                    f"(ref: {symbol_set.ref}, team: {symbol_set.team_id}): {str(e)}"
                )

        total_processed += len(symbol_sets)
        context.log.info(
            f"Processed {total_processed} symbol sets so far (deleted: {total_deleted}, failed: {total_failed})"
        )

    if total_failed > 0:
        context.log.warning(f"Failed to delete {total_failed} symbol sets out of {total_processed}")

    return dagster.MaterializeResult(
        metadata={
            "objects_processed": dagster.MetadataValue.int(total_processed),
            "objects_deleted": dagster.MetadataValue.int(total_deleted),
            "objects_failed": dagster.MetadataValue.int(total_failed),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


symbol_set_cleanup_job = dagster.define_asset_job(
    name="symbol_set_cleanup_job",
    selection=[symbol_set_cleanup.key],
    tags={"owner": JobOwners.TEAM_ERROR_TRACKING.value},
)


@dagster.schedule(
    job=symbol_set_cleanup_job,
    cron_schedule="0 * * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def hourly_symbol_set_cleanup_schedule(context):
    return dagster.RunRequest(
        run_key=f"symbol_set_cleanup_{context.scheduled_execution_time.strftime('%Y%m%d_%H%M%S')}",
    )
