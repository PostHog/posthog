import os
from datetime import UTC, datetime, timedelta

import dagster
import pydantic
from dagster import AssetExecutionContext, MetadataValue

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tags_context
from posthog.dags.common import JobOwners, dagster_tags

from products.web_analytics.dags.web_pre_aggregated_accuracy import build_accuracy_comparison_query
from products.web_analytics.dags.web_preaggregated_utils import (
    TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
)

WATCHDOG_CRON_SCHEDULE = os.getenv("WEB_ANALYTICS_WATCHDOG_CRON_SCHEDULE", "0 6 * * *")
DEFAULT_LOOKBACK_DAYS = int(os.getenv("WEB_ANALYTICS_WATCHDOG_LOOKBACK_DAYS", "7"))
DEFAULT_TOLERANCE_PCT = float(os.getenv("WEB_ANALYTICS_WATCHDOG_TOLERANCE_PCT", "5.0"))


class WatchdogConfig(dagster.Config):
    team_id: int = pydantic.Field(
        default=int(TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS),
        description="Team ID to check accuracy for",
    )
    lookback_days: int = pydantic.Field(
        default=DEFAULT_LOOKBACK_DAYS,
        description="Number of recent days to check",
    )
    tolerance_pct: float = pydantic.Field(
        default=DEFAULT_TOLERANCE_PCT,
        description="Maximum acceptable percentage difference before flagging a partition",
    )
    dry_run: bool = pydantic.Field(
        default=True,
        description="When True, only logs findings without triggering remediation",
    )


def check_partition_accuracy(
    context: AssetExecutionContext,
    team_id: int,
    partition_date: str,
    tolerance_pct: float,
) -> dict:
    """Run accuracy comparison for a single day partition and return the result."""
    query = build_accuracy_comparison_query(team_id, partition_date, partition_date)

    with tags_context(kind="dagster", dagster=dagster_tags(context)):
        result = sync_execute(query, settings=WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS)

    if not result:
        return {
            "partition_date": partition_date,
            "status": "NO_DATA",
            "regular_count": 0,
            "pre_aggregated_count": 0,
            "pct_difference": 0.0,
            "within_tolerance": True,
            "quality_status": "NO_DATA",
        }

    row = result[0]
    pct_difference = float(row[4])
    within_tolerance = pct_difference <= tolerance_pct

    quality_status: str
    if pct_difference <= 1:
        quality_status = "GOOD"
    elif pct_difference <= 5:
        quality_status = "FAIR"
    else:
        quality_status = "POOR"

    return {
        "partition_date": partition_date,
        "status": "CHECKED",
        "regular_count": int(row[2]),
        "pre_aggregated_count": int(row[3]),
        "pct_difference": pct_difference,
        "within_tolerance": within_tolerance,
        "quality_status": quality_status,
    }


def build_remediation_configs(failing_partitions: list[dict]) -> list[dict]:
    """Build ready-to-execute Dagster run configs for partitions that need recreation."""
    configs = []
    for partition in failing_partitions:
        configs.append(
            {
                "partition_key": partition["partition_date"],
                "job_name": "web_pre_aggregate_job",
                "run_config": {
                    "ops": {
                        "web_pre_aggregated_bounces": {"config": {}},
                        "web_pre_aggregated_stats": {"config": {}},
                    }
                },
                "tags": {
                    "triggered_by": "watchdog_remediation",
                    "reason": f"accuracy_below_tolerance ({partition['pct_difference']:.2f}% > {partition.get('tolerance_pct', 'N/A')}%)",
                },
            }
        )
    return configs


@dagster.asset(
    name="web_analytics_watchdog",
    group_name="web_analytics_v2",
    description=(
        "Watchdog that monitors pre-aggregated data accuracy across recent partitions. "
        "Identifies partitions with precision loss and produces remediation configs. "
        "Runs in dry-run mode by default (log-only, no automatic re-materialization)."
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_watchdog(context: AssetExecutionContext, config: WatchdogConfig) -> dagster.MaterializeResult:
    team_id = config.team_id
    lookback_days = config.lookback_days
    tolerance_pct = config.tolerance_pct
    dry_run = config.dry_run

    context.log.info(
        f"Watchdog starting: team_id={team_id}, lookback_days={lookback_days}, "
        f"tolerance_pct={tolerance_pct}%, dry_run={dry_run}"
    )

    end_date = (datetime.now(UTC) - timedelta(days=1)).date()
    start_date = end_date - timedelta(days=lookback_days - 1)

    partition_results: list[dict] = []
    failing_partitions: list[dict] = []
    errors: list[dict] = []

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        context.log.info(f"Checking partition {date_str}")

        try:
            result = check_partition_accuracy(context, team_id, date_str, tolerance_pct)
            partition_results.append(result)

            if not result["within_tolerance"]:
                result["tolerance_pct"] = tolerance_pct
                failing_partitions.append(result)
                context.log.warning(
                    f"Partition {date_str}: OUTSIDE TOLERANCE "
                    f"(diff={result['pct_difference']:.2f}%, threshold={tolerance_pct}%, "
                    f"regular={result['regular_count']}, pre_agg={result['pre_aggregated_count']})"
                )
            else:
                context.log.info(
                    f"Partition {date_str}: OK "
                    f"(diff={result['pct_difference']:.2f}%, status={result['quality_status']})"
                )
        except Exception as e:
            error_entry = {"partition_date": date_str, "error": str(e)}
            errors.append(error_entry)
            context.log.exception(f"Partition {date_str}: ERROR - {e}")

        current_date += timedelta(days=1)

    total_checked = len(partition_results)
    total_passing = total_checked - len(failing_partitions)
    accuracy_rate = (total_passing / max(total_checked, 1)) * 100

    if accuracy_rate >= 95:
        overall_status = "EXCELLENT"
    elif accuracy_rate >= 90:
        overall_status = "GOOD"
    elif accuracy_rate >= 80:
        overall_status = "FAIR"
    else:
        overall_status = "POOR"

    remediation_configs = build_remediation_configs(failing_partitions) if failing_partitions else []

    context.log.info(
        f"Watchdog complete: {overall_status} - "
        f"{total_passing}/{total_checked} partitions within tolerance ({accuracy_rate:.1f}%), "
        f"{len(failing_partitions)} need remediation, {len(errors)} errors"
    )

    if dry_run and failing_partitions:
        context.log.info(
            f"DRY RUN: {len(remediation_configs)} partition(s) would be re-materialized: "
            f"{[c['partition_key'] for c in remediation_configs]}"
        )

    failing_rows_md = "\n".join(
        f"| {p['partition_date']} "
        f"| {p['regular_count']:,} "
        f"| {p['pre_aggregated_count']:,} "
        f"| {p['pct_difference']:.2f}% "
        f"| {p['quality_status']} |"
        for p in failing_partitions
    )

    failing_table_md = (
        (
            "| Date | Regular Count | Pre-Aggregated Count | Diff % | Status |\n"
            "|------|---------------|----------------------|--------|--------|\n"
            f"{failing_rows_md}"
        )
        if failing_partitions
        else "No failing partitions"
    )

    all_rows_md = "\n".join(
        f"| {p['partition_date']} "
        f"| {p['regular_count']:,} "
        f"| {p['pre_aggregated_count']:,} "
        f"| {p['pct_difference']:.2f}% "
        f"| {'YES' if p['within_tolerance'] else 'NO'} "
        f"| {p['quality_status']} |"
        for p in partition_results
    )

    all_partitions_md = (
        (
            "| Date | Regular Count | Pre-Aggregated Count | Diff % | Within Tolerance | Status |\n"
            "|------|---------------|----------------------|--------|------------------|--------|\n"
            f"{all_rows_md}"
        )
        if partition_results
        else "No partitions checked"
    )

    return dagster.MaterializeResult(
        metadata={
            "team_id": MetadataValue.int(team_id),
            "date_range": MetadataValue.text(f"{start_date} to {end_date}"),
            "lookback_days": MetadataValue.int(lookback_days),
            "tolerance_pct": MetadataValue.float(tolerance_pct),
            "dry_run": MetadataValue.bool(dry_run),
            "overall_status": MetadataValue.text(overall_status),
            "total_checked": MetadataValue.int(total_checked),
            "total_passing": MetadataValue.int(total_passing),
            "accuracy_rate": MetadataValue.float(accuracy_rate),
            "failing_partition_count": MetadataValue.int(len(failing_partitions)),
            "error_count": MetadataValue.int(len(errors)),
            "failing_partitions": MetadataValue.json(failing_partitions),
            "remediation_configs": MetadataValue.json(remediation_configs),
            "errors": MetadataValue.json(errors),
            "failing_partitions_table": MetadataValue.md(failing_table_md),
            "all_partitions_table": MetadataValue.md(all_partitions_md),
        },
    )


web_analytics_watchdog_job = dagster.define_asset_job(
    name="web_analytics_watchdog_job",
    selection=["web_analytics_watchdog"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
    },
)


@dagster.schedule(
    cron_schedule=WATCHDOG_CRON_SCHEDULE,
    job=web_analytics_watchdog_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
def web_analytics_watchdog_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest(
        run_key=f"watchdog_{datetime.now(UTC).strftime('%Y-%m-%d')}",
        tags={
            "triggered_by": "watchdog_schedule",
        },
    )
