from typing import TYPE_CHECKING, cast

import psycopg
from dagster import (
    AssetExecutionContext,
    DagsterRun,
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
    BACKFILL_MONTHS_PER_TICK,
    DEFAULT_CLICKHOUSE_SETTINGS,
    DUCKLAKE_ALIAS,
    DUCKLING_BACKFILL_CONCURRENCY_TAG,
    PARQUET_WRITER_SETTINGS,
    DucklingBackfillConfig,
    DucklingTarget,
    _compute_fanout,
    _DuckgresSession,
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
    # FINAL only deduplicates within a shard; argMax also reconciles versions across shards.
    return f"""
        SELECT team_id, group_type_index, group_key,
            tupleElement(latest, 1) AS group_properties,
            tupleElement(latest, 2) AS created_at,
            toDateTime64(tupleElement(latest, 3), 6) AS _timestamp,
            now64(6) AS _inserted_at
        FROM (
            SELECT team_id, group_type_index, group_key,
                argMax(tuple(group_properties, created_at, _timestamp), tuple(_timestamp, _offset)) AS latest
            FROM groups
            WHERE team_id = {int(team_id)}
            GROUP BY team_id, group_type_index, group_key
        )
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
        **settings_with_log_comment(context),
        **(config.clickhouse_settings or {}),
    }
    settings.setdefault("max_bytes_before_external_group_by", 10 * 1024**3)
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
    client.execute(export_sql, settings=settings)
    return s3_glob


def ensure_groups_table(
    conn: psycopg.Connection[tuple[object, ...]], table_name: str, config: DucklingBackfillConfig
) -> None:
    table = sql.Identifier(DUCKLAKE_ALIAS, "posthog", table_name)
    if config.delete_tables:
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


def replace_groups_snapshot(
    conn: psycopg.Connection[tuple[object, ...]], target: DucklingTarget, table_name: str, s3_glob: str
) -> int:
    files = _glob_run_files(conn, s3_glob)
    # Keep the old snapshot visible if any file registration fails, including a disconnected session.
    with conn.transaction():
        if files:
            rows = conn.execute(
                "SELECT data_file, delete_file FROM ducklake_list_files(%s, %s, schema => 'posthog')",
                (DUCKLAKE_ALIAS, table_name),
            ).fetchall()
            active_files = {str(row[0]): row[1] for row in rows}
            registered = set(files).intersection(active_files)
            # A committed-but-unacknowledged transaction must not register the same paths again.
            if registered == set(files) and all(active_files[path] is None for path in files):
                return len(files)
            if registered:
                raise ValueError("Groups export is partially registered; start a new backfill run")
        conn.execute(
            sql.SQL("DELETE FROM {} WHERE team_id = %s").format(sql.Identifier(DUCKLAKE_ALIAS, "posthog", table_name)),
            (target.team_id,),
        )
        for path in files:
            conn.execute(
                "CALL ducklake_add_data_files(%s, %s, %s, schema => 'posthog', allow_missing => true)",
                (DUCKLAKE_ALIAS, table_name, path),
            )
    return len(files)


def run_groups_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    team_id = int(context.partition_key)
    groups_snapshot_select_sql(team_id)
    if not config.cleanup_existing_partition_data:
        raise ValueError("Groups snapshots require cleanup_existing_partition_data=True")
    target = _resolve_duckling_target(team_id)
    table_name = resolve_groups_table(team_id)
    tags = dagster_tags(context)

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
    file_count = 0
    if s3_glob is not None and not config.skip_ducklake_registration:
        session = _DuckgresSession(context, target)
        try:
            session.run("ensure groups table", lambda conn: ensure_groups_table(conn, table_name, config))
            file_count = session.run(
                "replace groups snapshot", lambda conn: replace_groups_snapshot(conn, target, table_name, s3_glob)
            )
        finally:
            session.close()
    context.add_output_metadata({"team_id": team_id, "groups_table": table_name, "files_registered": file_count})
    if not config.dry_run and not config.skip_ducklake_registration:
        record_duckling_backfill_workload(
            team_id=team_id, dataset=GROUPS_DATASET, mode="full", files_registered=file_count, partitions_exported=1
        )


@asset(partitions_def=duckling_groups_partitions_def, tags=GROUPS_TAGS)
def duckling_groups_backfill(context: AssetExecutionContext, config: DucklingBackfillConfig) -> None:
    if config.dry_run or config.skip_ducklake_registration:
        run_groups_backfill(context, config)
        return
    team_id = int(context.partition_key)
    run_id = context.run.run_id
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


def _registers_snapshot(run: DagsterRun) -> bool:
    ops = cast(dict[str, dict[str, dict[str, object]]], run.run_config.get("ops", {}))
    config = ops.get("duckling_groups_backfill", {}).get("config", {})
    return not (config.get("dry_run", False) or config.get("skip_ducklake_registration", False))


@sensor(job=duckling_groups_backfill_job, minimum_interval_seconds=600, default_status=DefaultSensorStatus.RUNNING)
def duckling_groups_full_backfill_sensor(context: SensorEvaluationContext) -> SensorResult:
    backfills = list_enabled_backfill_team_memberships("groups_full_backfill_sensor")
    if not backfills:
        return SensorResult(run_requests=[])
    _repair_stale_running_statuses(context, GROUPS_DATASET)
    existing = set(context.instance.get_dynamic_partitions("duckling_groups_backfill"))
    new_partitions: list[str] = []
    requests: list[RunRequest] = []
    for membership in backfills:
        key = str(membership.team_id)
        runs = context.instance.get_runs(
            filters=RunsFilter(job_name=GROUPS_JOB_NAME, tags={"dagster/partition": key}), limit=1
        )
        latest = runs[0] if runs else None
        if latest is not None and _registers_snapshot(latest):
            if latest.is_success:
                continue
        if latest is not None and latest.status in ACTIVE_RUN_STATUSES:
            continue
        if len(requests) >= BACKFILL_MONTHS_PER_TICK:
            break
        if key not in existing:
            new_partitions.append(key)
        requests.append(RunRequest(partition_key=key, run_key=f"{key}_groups_{latest.run_id if latest else 'new'}"))
    return SensorResult(
        run_requests=requests,
        dynamic_partitions_requests=[duckling_groups_partitions_def.build_add_request(new_partitions)]
        if new_partitions
        else [],
    )
