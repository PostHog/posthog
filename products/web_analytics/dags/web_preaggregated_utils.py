import os
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Optional

import dagster
from dagster import Array, Backoff, DagsterRunStatus, Field, Jitter, RetryPolicy, RunsFilter, SkipReason

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG

TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS = os.getenv("TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS", 1 if DEBUG else 2)

INTRA_DAY_HOURLY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_INTRA_DAY_HOURLY_CRON_SCHEDULE", "*/20 * * * *")
HISTORICAL_DAILY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_HISTORICAL_DAILY_CRON_SCHEDULE", "0 1 * * *")

WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT = os.getenv("WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT", "2200")

# Dagster execution timeout constants (should be higher than ClickHouse timeouts)
DAGSTER_WEB_JOB_TIMEOUT = int(os.getenv("WEB_PREAGGREGATED_DAGSTER_JOB_TIMEOUT", "2400"))


web_analytics_retry_policy_def = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

# Shared ClickHouse settings for web analytics pre-aggregation
WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS = {
    "max_execution_time": WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT,
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
    "s3_truncate_on_insert": "1",
}

# Add higher partition limit for development environments (backfills)
if DEBUG:
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS["max_partitions_per_insert_block"] = "1000"


def format_clickhouse_settings(settings_dict: dict[str, str]) -> str:
    return ",".join([f"{key}={value}" for key, value in settings_dict.items()])


def merge_clickhouse_settings(base_settings: dict[str, str], extra_settings: Optional[str] = None) -> str:
    settings = base_settings.copy()

    if extra_settings:
        # Parse extra settings string and merge
        for setting in extra_settings.split(","):
            if "=" in setting:
                key, value = setting.strip().split("=", 1)
                settings[key.strip()] = value.strip()

    return format_clickhouse_settings(settings)


def get_partitions(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    table_name: str,
    filter_by_partition_window: bool = False,
) -> list[str]:
    partition_query = f"SELECT DISTINCT partition FROM system.parts WHERE table = '{table_name}' AND active = 1"

    if filter_by_partition_window and context.partition_time_window:
        start_datetime, end_datetime = context.partition_time_window
        start_partition = start_datetime.strftime("%Y%m%d")
        end_partition = end_datetime.strftime("%Y%m%d")
        partition_query += f" AND partition >= '{start_partition}' AND partition < '{end_partition}'"

    partitions_result = cluster.any_host_by_roles(
        lambda client: client.execute(partition_query), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ).result()
    context.log.info(f"Found {len(partitions_result)} partitions for {table_name}: {partitions_result}")
    return sorted([partition_row[0] for partition_row in partitions_result if partition_row and len(partition_row) > 0])


def drop_partitions_for_date_range(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, table_name: str, start_date: str, end_date: str
) -> None:
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current_date < end_date_obj:
        partition_id = current_date.strftime("%Y%m%d")

        def drop_partition(client, pid):
            return client.execute(f"ALTER TABLE {table_name} DROP PARTITION '{pid}'")

        try:
            cluster.any_host_by_roles(
                partial(drop_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
            ).result()
            context.log.info(f"Dropped partition {partition_id} from {table_name}")
        except Exception as e:
            context.log.info(f"Partition {partition_id} doesn't exist or couldn't be dropped: {e}")

        current_date += timedelta(days=1)


def sync_partitions_on_replicas(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, target_table: str
) -> None:
    context.log.info(f"Syncing replicas for {target_table} on all hosts")
    cluster.map_hosts_by_roles(
        lambda client: client.execute(f"SYSTEM SYNC REPLICA {target_table}"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ).result()


def swap_partitions_from_staging(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, target_table: str, staging_table: str
) -> None:
    staging_partitions = get_partitions(context, cluster, staging_table, filter_by_partition_window=True)
    context.log.info(f"Swapping partitions {staging_partitions} from {staging_table} to {target_table}")

    def replace_partition(client, pid):
        return client.execute(f"ALTER TABLE {target_table} REPLACE PARTITION '{pid}' FROM {staging_table}")

    for partition_id in staging_partitions:
        cluster.any_host_by_roles(
            partial(replace_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
        ).result()


def clear_all_staging_partitions(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, staging_table: str
) -> None:
    all_partitions = get_partitions(context, cluster, staging_table, filter_by_partition_window=False)

    if not all_partitions:
        context.log.info(f"No partitions found in {staging_table}")
        return

    context.log.info(f"Clearing {len(all_partitions)} partitions from {staging_table}: {all_partitions}")

    def drop_partition(client, pid):
        return client.execute(f"ALTER TABLE {staging_table} DROP PARTITION '{pid}'")

    for partition_id in all_partitions:
        try:
            cluster.any_host_by_roles(
                partial(drop_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
            ).result()
            context.log.info(f"Dropped partition {partition_id} from {staging_table}")
        except Exception as e:
            context.log.warning(f"Failed to drop partition {partition_id} from {staging_table}: {e}")


def recreate_staging_table(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    staging_table: str,
    replace_sql_func: Callable[[], str],
) -> None:
    """Recreate staging table on all hosts using REPLACE TABLE."""
    context.log.info(f"Recreating staging table {staging_table}")
    # We generate a uuid with force_unique_zk_path=True, which we want to be unique per the cluster
    # so we must get the result statement string here instead of inside the lambda to run the
    # exact command on each host, otherwise we would get a new uuid per host and replication
    # woudn't kick in.
    sql_statement = replace_sql_func()
    cluster.map_hosts_by_roles(
        lambda client: client.execute(sql_statement), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ).result()


# Shared config schema for daily processing
WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        is_required=False,
        description="List of team IDs to process - if not provided, uses ClickHouse dictionary configuration",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
}


def check_for_concurrent_runs(context: dagster.ScheduleEvaluationContext) -> Optional[SkipReason]:
    # Get the schedule name from the context
    schedule_name = context._schedule_name

    # Get the schedule definition from the repository to find the associated job
    schedule_def = context.repository_def.get_schedule_def(schedule_name)
    job_name = schedule_def.job_name

    run_records = context.instance.get_run_records(
        RunsFilter(
            job_name=job_name,
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.NOT_STARTED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(run_records) > 0:
        context.log.info(f"Skipping {job_name} due to {len(run_records)} active run(s)")
        return SkipReason(f"Skipping {job_name} run because another run of the same job is already active")

    return None
