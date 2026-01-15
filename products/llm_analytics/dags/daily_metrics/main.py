"""
Daily aggregation of LLMA (LLM Analytics) metrics.

Aggregates AI event counts from the events table into a daily metrics table
for efficient querying and cost analysis.
"""

from datetime import UTC, datetime, timedelta

import pandas as pd
import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, dagster_tags

from products.llm_analytics.dags.daily_metrics.config import config
from products.llm_analytics.dags.daily_metrics.utils import get_delete_query, get_insert_query

# Partition definition for daily aggregations
partition_def = DailyPartitionsDefinition(start_date=config.partition_start_date, end_offset=1)

# Backfill policy: process N days per run
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=config.max_partitions_per_run)

# ClickHouse settings for aggregation queries
LLMA_CLICKHOUSE_SETTINGS = {
    "max_execution_time": str(config.clickhouse_max_execution_time),
}


@dagster.asset(
    name="llma_metrics_daily",
    group_name="llma",
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": config.table_name},
    tags={"owner": JobOwners.TEAM_LLM_ANALYTICS.value},
)
def llma_metrics_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Daily aggregation of LLMA metrics.

    Aggregates AI event counts ($ai_trace, $ai_generation, $ai_span, $ai_embedding)
    by team and date into a long-format metrics table for efficient querying.

    Long format allows adding new metrics without schema changes.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    metric_date = context.partition_time_window[0].strftime("%Y-%m-%d")

    context.log.info(f"Aggregating LLMA metrics for {metric_date}")

    try:
        delete_query = get_delete_query(metric_date)
        sync_execute(delete_query, settings=LLMA_CLICKHOUSE_SETTINGS)

        insert_query = get_insert_query(metric_date)
        context.log.info(f"Metrics query: \n{insert_query}")
        sync_execute(insert_query, settings=LLMA_CLICKHOUSE_SETTINGS)

        # Query and log the metrics that were just aggregated
        metrics_query = f"""
            SELECT
                metric_name,
                count(DISTINCT team_id) as teams,
                sum(metric_value) as total_value
            FROM {config.table_name}
            WHERE date = '{metric_date}'
            GROUP BY metric_name
            ORDER BY metric_name
        """
        metrics_results = sync_execute(metrics_query)

        if metrics_results:
            df = pd.DataFrame(metrics_results, columns=["metric_name", "teams", "total_value"])
            context.log.info(f"Aggregated {len(df)} metric types for {metric_date}:\n{df.to_string(index=False)}")
        else:
            context.log.info(f"No AI events found for {metric_date}")

        context.log.info(f"Successfully aggregated LLMA metrics for {metric_date}")

    except Exception as e:
        raise dagster.Failure(f"Failed to aggregate LLMA metrics: {str(e)}") from e


# Define the job that runs the asset
llma_metrics_daily_job = dagster.define_asset_job(
    name="llma_metrics_daily_job",
    selection=["llma_metrics_daily"],
    tags={
        "owner": JobOwners.TEAM_LLM_ANALYTICS.value,
        "dagster/max_runtime": str(config.job_timeout),
    },
)


@dagster.schedule(
    cron_schedule=config.cron_schedule,
    job=llma_metrics_daily_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_LLM_ANALYTICS.value},
)
def llma_metrics_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition.

    Schedule configured in products.llm_analytics.dags.config.
    This aggregates AI event metrics from the events table into the
    llma_metrics_daily table for efficient querying.
    """
    # Calculate yesterday's partition
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    context.log.info(f"Scheduling LLMA metrics aggregation for {yesterday}")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "llma_metrics_daily": {"config": {}},
            }
        },
    )
