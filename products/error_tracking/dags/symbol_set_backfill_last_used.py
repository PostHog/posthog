from django.db import connection
from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners


class SymbolSetBackfillLastUsedConfig(dagster.Config):
    total_per_run: int = 300000
    batch_size: int = 10000


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
    today = timezone.now().date()
    total_updated = 0

    while total_updated < config.total_per_run:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE posthog_errortrackingsymbolset
                SET last_used = %s
                WHERE id IN (
                    SELECT id FROM posthog_errortrackingsymbolset
                    WHERE last_used IS NULL
                    LIMIT %s
                )
                """,
                [today, config.batch_size],
            )
            updated = cursor.rowcount

        if updated == 0:
            break

        total_updated += updated
        context.log.info(f"Updated {total_updated} symbol sets so far")

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
