from django.db import connection
from django.utils import timezone

import dagster
import pydantic

from posthog.dags.common import JobOwners

from products.error_tracking.backend.temporal.symbol_set_cleanup.types import SYMBOL_SET_CLEANUP_BUCKET_COUNT


class SymbolSetBackfillLastUsedConfig(dagster.Config):
    total_per_run: int = 300000
    batch_size: int = pydantic.Field(default=10000, gt=0)


def _backfill_last_used_bucket(*, bucket: int, batch_size: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE posthog_errortrackingsymbolset
            SET last_used = %s
            WHERE id IN (
                SELECT id FROM posthog_errortrackingsymbolset
                WHERE last_used IS NULL
                  AND get_byte(uuid_send(id), 15) = %s
                LIMIT %s
            )
            """,
            [timezone.now().date(), bucket, batch_size],
        )
        return cursor.rowcount


@dagster.asset
def symbol_set_backfill_last_used(
    context: dagster.AssetExecutionContext,
    config: SymbolSetBackfillLastUsedConfig,
) -> dagster.MaterializeResult:
    """
    Backfill last_used for symbol sets that don't have one.
    Runs hourly, updating rows in small batches to avoid long locks.
    Once all rows are backfilled this is a no-op.
    """
    total_updated = 0

    for bucket in range(SYMBOL_SET_CLEANUP_BUCKET_COUNT):
        while total_updated < config.total_per_run:
            batch_size = min(config.batch_size, config.total_per_run - total_updated)
            updated = _backfill_last_used_bucket(bucket=bucket, batch_size=batch_size)
            total_updated += updated

            if updated < batch_size:
                break

            context.log.info(f"Updated {total_updated} symbol sets so far")

        if total_updated >= config.total_per_run:
            break

    context.log.info(f"Backfilled last_used for {total_updated} symbol sets")

    return dagster.MaterializeResult(
        metadata={
            "total_updated": dagster.MetadataValue.int(total_updated),
        }
    )


symbol_set_backfill_last_used_job = dagster.define_asset_job(
    name="symbol_set_backfill_last_used_job",
    selection=[symbol_set_backfill_last_used.key],
    tags={"owner": JobOwners.TEAM_ERROR_TRACKING.value},
)


@dagster.schedule(
    job=symbol_set_backfill_last_used_job,
    cron_schedule="0 * * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def hourly_symbol_set_backfill_last_used_schedule(context):
    return dagster.RunRequest(
        run_key=f"symbol_set_backfill_last_used_{context.scheduled_execution_time.strftime('%Y%m%d_%H%M%S')}",
    )
