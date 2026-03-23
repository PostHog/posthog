from django.db import connection
from django.utils import timezone

import dagster

from posthog.dags.common import JobOwners


class SymbolSetBackfillLastUsedConfig(dagster.Config):
    batch_size: int = 300000


@dagster.asset
def symbol_set_backfill_last_used(
    context: dagster.AssetExecutionContext,
    config: SymbolSetBackfillLastUsedConfig,
) -> dagster.MaterializeResult:
    """
    Backfill last_used for symbol sets that don't have one.
    Runs hourly, updating a batch per run. Once all rows are backfilled this is a no-op.
    """
    today = timezone.now().date()

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

    context.log.info(f"Backfilled last_used for {updated} symbol sets")

    return dagster.MaterializeResult(
        metadata={
            "total_updated": dagster.MetadataValue.int(updated),
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
