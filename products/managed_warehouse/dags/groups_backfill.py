from typing import TYPE_CHECKING

from django.utils import timezone

import psycopg
from dagster import (
    AssetExecutionContext,
    DagsterRunStatus,
    DefaultSensorStatus,
    DynamicPartitionsDefinition,
    RunRequest,
    RunsFilter,
    SensorEvaluationContext,
    SensorResult,
    asset,
    define_asset_job,
    sensor,
)
from psycopg import sql

from posthog.hogql.escape_sql import escape_clickhouse_string

from posthog.clickhouse.cluster import NodeRole, Workload
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners
from posthog.dags.common.common import ACTIVE_RUN_STATUSES, dagster_tags, settings_with_log_comment
from posthog.dags.events_backfill_to_duckling import (
    DEFAULT_CLICKHOUSE_SETTINGS,
    DUCKLAKE_ALIAS,
    DUCKLING_BACKFILL_CONCURRENCY_TAG,
    PARQUET_WRITER_SETTINGS,
    DucklingBackfillConfig,
    DucklingTarget,
    _compute_fanout,
    _DuckgresSession,
    _execute_export_with_retry,
    _get_cluster,
    _glob_run_files,
    _repair_stale_running_statuses,
    _resolve_duckling_target,
    get_s3_url_for_clickhouse,
)

from products.data_warehouse.backend.facade.backfill_status import record_backfill_finished, record_backfill_started
from products.data_warehouse.backend.facade.models import ManagedWarehouseBackfillPartition
from products.managed_warehouse.backend.facade.metrics import record_duckling_backfill_workload, track_duckling_backfill
from products.managed_warehouse.backend.facade.team_state import (
    list_enabled_backfill_team_memberships,
    resolve_groups_table,
)

if TYPE_CHECKING:
    from clickhouse_driver import Client

GROUPS_DATASET = ManagedWarehouseBackfillPartition.Dataset.GROUPS
GROUPS_JOB_NAME = "duckling_groups_backfill_job"
GROUPS_SNAPSHOT_TAG = "groups_backfill/snapshot"
MAX_TEAMS_PER_TICK = 25
MAX_RUN_REQUESTS_PER_TICK = 3
RETRY_HISTORY_LIMIT = 6
RETRY_BASE_SECONDS = 600
GROUPS_TAGS = {"owner": JobOwners.TEAM_MANAGED_WAREHOUSE.value, **DUCKLING_BACKFILL_CONCURRENCY_TAG}
duckling_groups_partitions_def = DynamicPartitionsDefinition(name="duckling_groups_backfill")
GROUPS_COLUMN_TYPES = {
    "team_id": "BIGINT",
    "group_type_index": "UTINYINT",
    "group_key": "VARCHAR",
    "group_properties": "VARCHAR",
    "created_at": "TIMESTAMP WITH TIME ZONE",
    "_timestamp": "TIMESTAMP WITH TIME ZONE",
    "_inserted_at": "TIMESTAMP WITH TIME ZONE",
}


def groups_snapshot_select_sql(team_id: int) -> str:
    if team_id <= 0:
        raise ValueError("Groups backfill requires a positive team ID")
    return f"""
        SELECT team_id, group_type_index, group_key,
            group_properties, created_at,
            toDateTime64(_timestamp, 6) AS _timestamp,
            now64(6) AS _inserted_at
        FROM groups FINAL
        WHERE team_id = {int(team_id)}
    """


def export_groups_to_duckling_s3(
    context: AssetExecutionContext,
    client: "Client",
    config: DucklingBackfillConfig,
    target: DucklingTarget,
) -> str | None:
    path = f"backfill/groups/{target.team_id}/{context.run.run_id}/{{_partition_id}}.parquet"
    s3_url = get_s3_url_for_clickhouse(target.bucket, target.bucket_region, path)
    s3_glob = f"s3://{target.bucket}/{path.replace('{_partition_id}', '*')}"
    if config.dry_run:
        context.log.info(f"[DRY RUN] Would export the groups snapshot to {s3_glob}")
        return None

    settings = {
        **DEFAULT_CLICKHOUSE_SETTINGS,
        "max_memory_usage": 100 * 1024**3,
        **settings_with_log_comment(context),
        **(config.clickhouse_settings or {}),
    }
    settings.update(PARQUET_WRITER_SETTINGS)
    row_count = client.execute(
        "SELECT count() FROM groups WHERE team_id = %(team_id)s", {"team_id": target.team_id}, settings=settings
    )[0][0]
    fanout = _compute_fanout(int(row_count), config.target_rows_per_file, config.max_s3_file_fanout)
    export_sql = f"""
        INSERT INTO FUNCTION s3({escape_clickhouse_string(s3_url)}, 'Parquet')
        PARTITION BY toString(cityHash64(group_type_index, group_key) % {fanout})
        {groups_snapshot_select_sql(target.team_id)}
        SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """
    # A failed export can leave partial S3 objects; only register files after the whole query succeeds.
    _execute_export_with_retry(client, export_sql, settings, f"team_id={target.team_id}, full groups export")
    return s3_glob


def ensure_groups_table(
    conn: psycopg.Connection[tuple[object, ...]], table_name: str, config: DucklingBackfillConfig
) -> None:
    table = sql.Identifier(DUCKLAKE_ALIAS, "posthog", table_name)
    if config.delete_tables:
        if table_name == "groups":
            raise ValueError("Cannot drop the shared groups table; use a team snapshot replacement")
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
    if config.create_tables_if_missing:
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(DUCKLAKE_ALIAS, "posthog")))
        columns = sql.SQL(", ").join(
            sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(column_type))
            for name, column_type in GROUPS_COLUMN_TYPES.items()
        )
        conn.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(table, columns))
    if not config.skip_schema_validation:
        rows = conn.execute(sql.SQL("DESCRIBE {}").format(table)).fetchall()
        actual = {str(row[0]): str(row[1]) for row in rows}
        if actual != GROUPS_COLUMN_TYPES:
            raise ValueError(f"Groups table schema mismatch: expected {GROUPS_COLUMN_TYPES}, got {actual}")


def delete_groups_partition_data(
    conn: psycopg.Connection[tuple[object, ...]], target: DucklingTarget, table_name: str
) -> None:
    conn.execute(
        sql.SQL("DELETE FROM {} WHERE team_id = %s").format(sql.Identifier(DUCKLAKE_ALIAS, "posthog", table_name)),
        (target.team_id,),
    )


def register_groups_files_with_duckling(
    context: AssetExecutionContext,
    conn: psycopg.Connection[tuple[object, ...]],
    table_name: str,
    s3_glob: str,
) -> int:
    files = _glob_run_files(conn, s3_glob)
    if not files:
        context.log.info(f"No groups files produced for {s3_glob}, nothing to register")
        return 0
    context.log.info(f"Registering {len(files)} groups file(s) with DuckLake from {s3_glob}")
    for path in files:
        conn.execute(
            "CALL ducklake_add_data_files(%s, %s, %s, schema => 'posthog', allow_missing => true)",
            (DUCKLAKE_ALIAS, table_name, path),
        )
    return len(files)


def run_groups_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    team_id = int(context.partition_key)
    groups_snapshot_select_sql(team_id)
    target = _resolve_duckling_target(team_id)
    table_name = resolve_groups_table(team_id)
    tags = dagster_tags(context)
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, target) if should_use_duckgres else None
    files_registered = 0
    try:
        if session is not None:
            session.run("ensure groups table", lambda conn: ensure_groups_table(conn, table_name, config))
            if config.cleanup_existing_partition_data:
                session.run("delete all groups", lambda conn: delete_groups_partition_data(conn, target, table_name))

        def export(client: "Client") -> str | None:
            with tags_context(kind="dagster", dagster=tags):
                return export_groups_to_duckling_s3(context, client, config, target)

        s3_glob = (
            _get_cluster()
            .any_host_by_role(
                fn=export, workload=Workload.OFFLINE if is_cloud() else Workload.DEFAULT, node_role=NodeRole.DATA
            )
            .result()
        )
        if s3_glob is not None and session is not None:

            def register_full_groups_files(conn: psycopg.Connection[tuple[object, ...]], glob: str = s3_glob) -> int:
                # Re-clear the team on replay because an unacknowledged registration may have committed.
                if config.cleanup_existing_partition_data:
                    delete_groups_partition_data(conn, target, table_name)
                return register_groups_files_with_duckling(context, conn, table_name, glob)

            files_registered = session.run("register groups files (full)", register_full_groups_files)
    finally:
        if session is not None:
            session.close()
    context.add_output_metadata(
        {
            "team_id": team_id,
            "groups_table": table_name,
            "files_registered": files_registered,
        }
    )
    if not config.dry_run and not config.skip_ducklake_registration:
        record_duckling_backfill_workload(
            team_id=team_id,
            dataset=GROUPS_DATASET,
            mode="full",
            files_registered=files_registered,
            partitions_exported=1,
        )


@asset(partitions_def=duckling_groups_partitions_def, tags=GROUPS_TAGS)
def duckling_groups_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    if config.dry_run or config.skip_ducklake_registration:
        context.instance.add_run_tags(context.run.run_id, {GROUPS_SNAPSHOT_TAG: "false"})
        run_groups_backfill(context, config)
        return
    team_id = int(context.partition_key)
    run_id = context.run.run_id
    context.instance.add_run_tags(run_id, {GROUPS_SNAPSHOT_TAG: "true"})
    record_backfill_started(team_id=team_id, dataset=GROUPS_DATASET, partition_key=context.partition_key, run_id=run_id)
    with track_duckling_backfill(team_id=team_id, dataset=GROUPS_DATASET, mode="full"):
        try:
            run_groups_backfill(context, config)
        except Exception as error:
            record_backfill_finished(
                team_id=team_id, dataset=GROUPS_DATASET, partition_key=context.partition_key, run_id=run_id, error=error
            )
            raise
        record_backfill_finished(
            team_id=team_id, dataset=GROUPS_DATASET, partition_key=context.partition_key, run_id=run_id
        )


duckling_groups_backfill_job = define_asset_job(
    name=GROUPS_JOB_NAME, selection=["duckling_groups_backfill"], tags=GROUPS_TAGS
)


@sensor(job=duckling_groups_backfill_job, minimum_interval_seconds=600, default_status=DefaultSensorStatus.STOPPED)
def duckling_groups_full_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    backfills = sorted(
        list_enabled_backfill_team_memberships("groups_full_backfill_sensor"), key=lambda row: row.team_id
    )
    if not backfills:
        return SensorResult(run_requests=[])
    _repair_stale_running_statuses(context, GROUPS_DATASET)
    after_team = int(context.cursor or "0")
    candidates = [row for row in backfills if row.team_id > after_team] or backfills
    existing = set(context.instance.get_dynamic_partitions("duckling_groups_backfill"))
    new_partitions: list[str] = []
    requests: list[RunRequest] = []
    for membership in candidates[:MAX_TEAMS_PER_TICK]:
        after_team = membership.team_id
        key = str(membership.team_id)
        active = context.instance.get_runs(
            filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags={"dagster/partition": key}, statuses=ACTIVE_RUN_STATUSES),
            limit=1,
        )
        if active:
            continue
        history = context.instance.get_run_records(
            filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags={"dagster/partition": key, GROUPS_SNAPSHOT_TAG: "true"}),
            limit=RETRY_HISTORY_LIMIT,
        )
        latest = history[0] if history else None
        if latest is not None and latest.dagster_run.is_success:
            continue
        if latest is not None:
            failures = 0
            for record in history:
                if record.dagster_run.status not in (DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED):
                    break
                failures += 1
            retry_after = RETRY_BASE_SECONDS * 2 ** max(failures - 1, 0)
            ended_at = latest.end_time or latest.update_timestamp.timestamp()
            if timezone.now().timestamp() < ended_at + retry_after:
                continue
        if key not in existing:
            new_partitions.append(key)
        requests.append(
            RunRequest(
                partition_key=key,
                run_key=f"{key}_groups_{latest.dagster_run.run_id if latest else 'new'}",
                tags={GROUPS_SNAPSHOT_TAG: "true"},
            )
        )
        if len(requests) >= MAX_RUN_REQUESTS_PER_TICK:
            break
    return SensorResult(
        run_requests=requests,
        cursor=str(after_team),
        dynamic_partitions_requests=[duckling_groups_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )
