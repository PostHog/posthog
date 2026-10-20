from datetime import UTC, datetime, timedelta
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
    is_full_export_partition,
    parse_partition_key_dates,
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
GROUPS_REFRESH_DATE_TAG = "groups_backfill/refresh_date"
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


def groups_snapshot_select_sql(team_id: int, date: datetime | None = None) -> str:
    if team_id <= 0:
        raise ValueError("Groups backfill requires a positive team ID")
    date_filter = ""
    if date is not None:
        start = escape_clickhouse_string(date.strftime("%Y-%m-%d"))
        end = escape_clickhouse_string((date + timedelta(days=1)).strftime("%Y-%m-%d"))
        date_filter = f"AND _timestamp >= toDateTime({start}, 'UTC') AND _timestamp < toDateTime({end}, 'UTC')"
    return f"""
        SELECT team_id, group_type_index, group_key,
            group_properties, created_at,
            toDateTime64(_timestamp, 6) AS _timestamp,
            now64(6) AS _inserted_at
        FROM groups FINAL
        WHERE team_id = {int(team_id)} {date_filter}
    """


def export_groups_to_duckling_s3(
    context: AssetExecutionContext,
    client: "Client",
    config: DucklingBackfillConfig,
    target: DucklingTarget,
    date: datetime | None = None,
) -> str | None:
    period = f"/{date.strftime('%Y-%m-%d')}" if date is not None else ""
    path = f"backfill/groups/{target.team_id}{period}/{context.run.run_id}/{{_partition_id}}.parquet"
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
    count_sql = "SELECT count() FROM groups WHERE team_id = %(team_id)s"
    count_params: dict[str, int | str] = {"team_id": target.team_id}
    if date is not None:
        count_sql += " AND _timestamp >= toDateTime(%(date)s, 'UTC') AND _timestamp < toDateTime(%(next_date)s, 'UTC')"
        count_params.update(date=date.strftime("%Y-%m-%d"), next_date=(date + timedelta(days=1)).strftime("%Y-%m-%d"))
    row_count = client.execute(count_sql, count_params, settings=settings)[0][0]
    fanout = _compute_fanout(int(row_count), config.target_rows_per_file, config.max_s3_file_fanout)
    export_sql = f"""
        INSERT INTO FUNCTION s3({escape_clickhouse_string(s3_url)}, 'Parquet')
        PARTITION BY toString(cityHash64(group_type_index, group_key) % {fanout})
        {groups_snapshot_select_sql(target.team_id, date)}
        SETTINGS s3_truncate_on_insert=1, use_hive_partitioning=0
    """
    # A failed export can leave partial S3 objects; only register files after the whole query succeeds.
    info = f"team_id={target.team_id}, date={date.strftime('%Y-%m-%d') if date is not None else 'full'}"
    _execute_export_with_retry(client, export_sql, settings, info)
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
    conn: psycopg.Connection[tuple[object, ...]],
    target: DucklingTarget,
    table_name: str,
    date: datetime | None = None,
) -> None:
    query = sql.SQL("DELETE FROM {} WHERE team_id = %s").format(sql.Identifier(DUCKLAKE_ALIAS, "posthog", table_name))
    params: tuple[object, ...] = (target.team_id,)
    if date is not None:
        query += sql.SQL(" AND _timestamp >= %s AND _timestamp < %s")
        params += (date.strftime("%Y-%m-%d"), (date + timedelta(days=1)).strftime("%Y-%m-%d"))
    conn.execute(query, params)


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
    partition_key = context.partition_key
    is_full = is_full_export_partition(partition_key)
    dates: list[datetime | None]
    if is_full:
        team_id = int(partition_key)
        dates = [None]
    else:
        team_id, partition_dates = parse_partition_key_dates(partition_key)
        dates = list(partition_dates)
    groups_snapshot_select_sql(team_id)
    mode = "full" if is_full else "daily"
    target = _resolve_duckling_target(team_id)
    table_name = resolve_groups_table(team_id)
    tags = dagster_tags(context)
    should_use_duckgres = not (config.dry_run or config.skip_ducklake_registration)
    session = _DuckgresSession(context, target) if should_use_duckgres else None
    files_registered = 0
    partitions_exported = 0
    try:
        if session is not None:
            session.run("ensure groups table", lambda conn: ensure_groups_table(conn, table_name, config))
        for partition_date in dates:
            date_label = partition_date.strftime("%Y-%m-%d") if partition_date is not None else "full"
            if session is not None and config.cleanup_existing_partition_data:

                def delete_groups_partition(
                    conn: psycopg.Connection[tuple[object, ...]], date: datetime | None = partition_date
                ) -> None:
                    delete_groups_partition_data(conn, target, table_name, date)

                session.run(f"delete groups partition {date_label}", delete_groups_partition)

            def export(client: "Client", date: datetime | None = partition_date) -> str | None:
                with tags_context(kind="dagster", dagster=tags):
                    return export_groups_to_duckling_s3(context, client, config, target, date)

            s3_glob = (
                _get_cluster()
                .any_host_by_role(
                    fn=export, workload=Workload.OFFLINE if is_cloud() else Workload.DEFAULT, node_role=NodeRole.DATA
                )
                .result()
            )
            if s3_glob is not None:
                partitions_exported += 1
                if session is not None:

                    def register_groups_files(
                        conn: psycopg.Connection[tuple[object, ...]],
                        glob: str = s3_glob,
                        date: datetime | None = partition_date,
                    ) -> int:
                        # Re-clear the partition on replay because an unacknowledged registration may have committed.
                        if config.cleanup_existing_partition_data:
                            delete_groups_partition_data(conn, target, table_name, date)
                        return register_groups_files_with_duckling(context, conn, table_name, glob)

                    files_registered += session.run(f"register groups files {date_label}", register_groups_files)
    finally:
        if session is not None:
            session.close()
    context.add_output_metadata(
        {
            "team_id": team_id,
            "partition_key": partition_key,
            "export_mode": mode,
            "groups_table": table_name,
            "files_registered": files_registered,
            "partitions_exported": partitions_exported,
        }
    )
    if not config.dry_run and not config.skip_ducklake_registration:
        record_duckling_backfill_workload(
            team_id=team_id,
            dataset=GROUPS_DATASET,
            mode=mode,
            files_registered=files_registered,
            partitions_exported=partitions_exported,
        )


@asset(partitions_def=duckling_groups_partitions_def, tags=GROUPS_TAGS)
def duckling_groups_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    if config.dry_run or config.skip_ducklake_registration:
        context.instance.add_run_tags(context.run.run_id, {GROUPS_SNAPSHOT_TAG: "false"})
        run_groups_backfill(context, config)
        return
    is_full = is_full_export_partition(context.partition_key)
    team_id = int(context.partition_key) if is_full else parse_partition_key_dates(context.partition_key)[0]
    mode = "full" if is_full else "daily"
    run_id = context.run.run_id
    context.instance.add_run_tags(run_id, {GROUPS_SNAPSHOT_TAG: "true"})
    record_backfill_started(team_id=team_id, dataset=GROUPS_DATASET, partition_key=context.partition_key, run_id=run_id)
    with track_duckling_backfill(team_id=team_id, dataset=GROUPS_DATASET, mode=mode):
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


def _groups_snapshot_run_request(
    context: SensorEvaluationContext, key: str, *, refresh_daily: bool, now: datetime
) -> RunRequest | None:
    full_partition_tags = {"dagster/partition": key}
    successes = context.instance.get_run_records(
        filters=RunsFilter(
            job_name=GROUPS_JOB_NAME,
            tags={**full_partition_tags, GROUPS_SNAPSHOT_TAG: "true"},
            statuses=[DagsterRunStatus.SUCCESS],
        ),
        limit=1,
    )
    if refresh_daily:
        if not successes:
            return None
        if context.instance.get_runs(
            filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags=full_partition_tags, statuses=ACTIVE_RUN_STATUSES),
            limit=1,
        ):
            return None
        key = f"{key}_{(now - timedelta(days=1)).date().isoformat()}"
    elif successes:
        return None
    partition_tags = {"dagster/partition": key}
    if context.instance.get_runs(
        filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags=partition_tags, statuses=ACTIVE_RUN_STATUSES), limit=1
    ):
        return None
    history = context.instance.get_run_records(
        filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags={**partition_tags, GROUPS_SNAPSHOT_TAG: "true"}),
        limit=RETRY_HISTORY_LIMIT,
    )
    latest = history[0] if history else None
    if latest is not None and latest.dagster_run.is_success:
        return None
    if latest is not None and latest.dagster_run.status in (DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED):
        failures = 0
        for record in history:
            if record.dagster_run.status not in (DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED):
                break
            failures += 1
        retry_after = RETRY_BASE_SECONDS * 2 ** (failures - 1)
        ended_at = latest.end_time or latest.update_timestamp.timestamp()
        if now.timestamp() < ended_at + retry_after:
            return None
    return RunRequest(
        partition_key=key,
        run_key=f"{key}_groups_{latest.dagster_run.run_id if latest else 'new'}",
        tags={
            GROUPS_SNAPSHOT_TAG: "true",
            **({GROUPS_REFRESH_DATE_TAG: key.split("_", 1)[1]} if refresh_daily else {}),
        },
    )


def _groups_snapshot_sensor_result(context: SensorEvaluationContext, *, refresh_daily: bool) -> SensorResult:
    call_site = "groups_daily_backfill_sensor" if refresh_daily else "groups_full_backfill_sensor"
    backfills = sorted(list_enabled_backfill_team_memberships(call_site), key=lambda row: row.team_id)
    if not backfills:
        return SensorResult(run_requests=[])
    _repair_stale_running_statuses(context, GROUPS_DATASET)
    after_team = int(context.cursor or "0")
    candidates = [row for row in backfills if row.team_id > after_team] or backfills
    existing = set(context.instance.get_dynamic_partitions("duckling_groups_backfill"))
    new_partitions: list[str] = []
    requests: list[RunRequest] = []
    now = timezone.now().astimezone(UTC)
    for membership in candidates[:MAX_TEAMS_PER_TICK]:
        after_team = membership.team_id
        key = str(membership.team_id)
        request = _groups_snapshot_run_request(context, key, refresh_daily=refresh_daily, now=now)
        if request is None:
            continue
        if request.partition_key is not None and request.partition_key not in existing:
            new_partitions.append(request.partition_key)
        requests.append(request)
        if len(requests) >= MAX_RUN_REQUESTS_PER_TICK:
            break
    return SensorResult(
        run_requests=requests,
        cursor=str(after_team),
        dynamic_partitions_requests=[duckling_groups_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )


@sensor(job=duckling_groups_backfill_job, minimum_interval_seconds=600, default_status=DefaultSensorStatus.STOPPED)
def duckling_groups_full_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    return _groups_snapshot_sensor_result(context, refresh_daily=False)


@sensor(job=duckling_groups_backfill_job, minimum_interval_seconds=600, default_status=DefaultSensorStatus.STOPPED)
def duckling_groups_daily_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    return _groups_snapshot_sensor_result(context, refresh_daily=True)
