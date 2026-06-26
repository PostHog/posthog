from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from django.conf import settings
from django.db import close_old_connections

import psycopg
import structlog
from psycopg import sql

from posthog.ducklake.common import duckgres_data_imports_schema, get_duckgres_config_for_org
from posthog.ducklake.storage import setup_duckgres_session
from posthog.models import Team

from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)

logger = structlog.get_logger(__name__)

DUCKGRES_APPLY_TABLE = "_posthog_source_batch_duckgres_apply"

# Duckgres-side apply markers older than this are pruned opportunistically at the
# start of each run. Must comfortably exceed the queue's eligibility window
# (PARTITION_PRUNING_INTERVAL, 14d) — the ordering gate and has_applied read them.
APPLY_MARKER_RETENTION_DAYS = 30

EXTRACT_READ_SECRET_NAME = "posthog_extract_read"


class DuckgresBatchAlreadyAppliedError(Exception):
    """A concurrent processor applied this batch first; our write was rolled back."""


@dataclass(frozen=True)
class DuckgresColumn:
    name: str
    type_sql: str


@dataclass(frozen=True)
class BatchApplyOperation:
    kind: Literal["replace", "create", "insert", "merge"]
    ensure_target_columns: bool = False
    primary_keys: list[str] | None = None
    version_keys: list[str] | None = None


def process_batch(batch: PendingBatch) -> None:
    # Threads are reused across batches; drop stale app-DB connections so the ORM
    # reads below reconnect instead of failing every attempt after a DB bounce.
    close_old_connections()

    job = ExternalDataJob.objects.select_related("schema", "schema__source").get(
        id=batch.job_id,
        team_id=batch.team_id,
    )
    schema = job.schema
    if schema is None:
        raise ValueError(f"ExternalDataJob {batch.job_id} has no schema")

    with _connect_to_duckgres(batch.team_id) as conn:
        # The sink only reads parquet over S3; httpfs is bundled in the duckgres
        # worker image so INSTALL is a local no-op. Do NOT add extensions that are
        # not bundled (e.g. delta): egress-restricted workers silently drop the
        # CDN download and the statement hangs.
        setup_duckgres_session(conn, extensions=("httpfs",))
        _create_extract_read_secret(conn)
        try:
            _process_batch(conn, batch, schema)
        except DuckgresBatchAlreadyAppliedError:
            # A concurrent processor (lost advisory-lock session + recovery sweep)
            # won the marker insert; its committed write is the canonical one and
            # ours rolled back. Treat as applied.
            logger.info(
                "duckgres_batch_applied_by_concurrent_processor",
                team_id=batch.team_id,
                schema_id=batch.schema_id,
                run_uuid=batch.run_uuid,
                batch_index=batch.batch_index,
            )


def _connect_to_duckgres(team_id: int) -> psycopg.Connection[Any]:
    team = Team.objects.only("organization_id").get(id=team_id)
    config = get_duckgres_config_for_org(str(team.organization_id))
    return psycopg.connect(
        host=config["DUCKGRES_HOST"],
        port=config["DUCKGRES_PORT"],
        dbname=config["DUCKGRES_DATABASE"],
        user=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
        autocommit=True,
        # A half-open connection to a dead worker would otherwise block the sync
        # thread for the OS TCP timeout (hours). Keepalives bound it to ~2 minutes;
        # the consumer's stuck-batch watchdog is the backstop above that.
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=60,
        keepalives_interval=15,
        keepalives_count=4,
    )


def _create_extract_read_secret(conn: psycopg.Connection[Any]) -> None:
    """Grant this duckgres session read access to PostHog's extract bucket.

    read_parquet() executes on the duckgres worker, whose ambient credentials are
    org-scoped to the org's own lake bucket — they cannot read the internal
    DATAWAREHOUSE_BUCKET where v3 batches live. Mint short-lived credentials from
    the consumer's own identity and inject them as a session secret SCOPEd to the
    extract bucket, so it wins prefix resolution there and nowhere else.
    """
    bucket = settings.DATAWAREHOUSE_BUCKET
    scope = f"s3://{bucket}"

    if settings.USE_LOCAL_SETUP:
        parts = [
            "TYPE S3",
            f"KEY_ID {_sql_str(settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY)}",
            f"SECRET {_sql_str(settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET)}",
            f"ENDPOINT {_sql_str(settings.OBJECT_STORAGE_ENDPOINT.replace('http://', '').replace('https://', ''))}",
            "URL_STYLE 'path'",
            "USE_SSL false",
            f"SCOPE {_sql_str(scope)}",
        ]
    else:
        import boto3

        session = boto3.Session()
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials available to read the extract bucket from duckgres")
        frozen = creds.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            raise RuntimeError("AWS credential chain resolved without an access key pair")
        parts = [
            "TYPE S3",
            f"KEY_ID {_sql_str(frozen.access_key)}",
            f"SECRET {_sql_str(frozen.secret_key)}",
            f"REGION {_sql_str(session.region_name or 'us-east-1')}",
            f"SCOPE {_sql_str(scope)}",
        ]
        if frozen.token:
            parts.insert(3, f"SESSION_TOKEN {_sql_str(frozen.token)}")

    conn.execute(
        f"CREATE OR REPLACE SECRET {EXTRACT_READ_SECRET_NAME} ({', '.join(parts)})"  # noqa: S608
    )


def _sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _process_batch(conn: psycopg.Connection[Any], batch: PendingBatch, schema: ExternalDataSchema) -> None:
    duckgres_schema = _duckgres_schema_name(batch.team_id)
    duckgres_table = _duckgres_table_name(schema)

    conn.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(duckgres_schema)),
    )

    if batch.sync_type == "cdc":
        raise ValueError("Duckgres batch sink does not support CDC batches yet")

    _ensure_duckgres_apply_table(conn, duckgres_schema)
    if batch.batch_index == 0 and not batch.is_final_batch:
        _prune_duckgres_apply_markers(conn, duckgres_schema)
    if _has_duckgres_batch_applied(conn, duckgres_schema, batch=batch):
        logger.info(
            "duckgres_batch_already_applied",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            run_uuid=batch.run_uuid,
            batch_index=batch.batch_index,
        )
        return

    parquet_schema = _read_parquet_schema(conn, batch.s3_path)
    columns = [column.name for column in parquet_schema]
    operation = _plan_batch_operation(
        conn,
        batch,
        duckgres_schema=duckgres_schema,
        duckgres_table=duckgres_table,
    )

    if operation.kind == "replace":
        logger.info(
            "duckgres_replacing_table_from_batch",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            batch_index=batch.batch_index,
            table=duckgres_table,
        )

    with conn.transaction():
        if operation.ensure_target_columns:
            _ensure_target_columns(conn, duckgres_schema, duckgres_table, parquet_schema)
        _apply_batch_operation(
            conn,
            operation,
            duckgres_schema=duckgres_schema,
            duckgres_table=duckgres_table,
            s3_path=batch.s3_path,
            columns=columns,
        )
        _mark_duckgres_batch_applied(conn, duckgres_schema, batch=batch)
        return


def _duckgres_schema_name(team_id: int) -> str:
    # Resolves to posthog_data_imports_<table_suffix> when the team has set one
    # (DuckLakeBackfill.table_suffix — the same suffix that names its
    # events/persons tables), else the legacy posthog_data_imports_team_<id>.
    return duckgres_data_imports_schema(team_id)


def _duckgres_table_name(schema: ExternalDataSchema) -> str:
    source_type = schema.source.source_type
    normalized_name = schema.normalized_name
    raw_name = (
        f"{source_type}_{schema.source.prefix}_{normalized_name}"
        if schema.source.prefix
        else f"{source_type}_{normalized_name}"
    )
    return NamingConvention.normalize_identifier(raw_name, max_length=63)


def _should_replace_table(batch: PendingBatch) -> bool:
    if batch.batch_index != 0 or batch.is_resume:
        return False
    if batch.sync_type == "full_refresh":
        return True
    if batch.sync_type == "incremental":
        return batch.is_first_ever_sync
    return False


def _plan_batch_operation(
    conn: psycopg.Connection[Any],
    batch: PendingBatch,
    *,
    duckgres_schema: str,
    duckgres_table: str,
) -> BatchApplyOperation:
    if _should_replace_table(batch):
        return BatchApplyOperation(kind="replace")

    if not _table_exists(conn, duckgres_schema, duckgres_table):
        return BatchApplyOperation(kind="create")

    if batch.sync_type == "incremental":
        if batch.is_first_ever_sync:
            return BatchApplyOperation(kind="insert", ensure_target_columns=True)

        primary_keys = _primary_keys(batch)
        if not primary_keys:
            raise ValueError("Duckgres incremental batches require primary keys")
        return BatchApplyOperation(
            kind="merge",
            ensure_target_columns=True,
            primary_keys=primary_keys,
            version_keys=_version_keys(batch),
        )

    if batch.sync_type in ("full_refresh", "append"):
        return BatchApplyOperation(kind="insert", ensure_target_columns=True)

    raise ValueError(f"Unsupported Duckgres sync type: {batch.sync_type}")


def _table_exists(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str) -> bool:
    cursor = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
            AND table_name = %s
        LIMIT 1
        """,
        [duckgres_schema, duckgres_table],
    )
    return cursor.fetchone() is not None


def _replace_table(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str) -> None:
    conn.execute(
        sql.SQL("CREATE OR REPLACE TABLE {}.{} AS SELECT * FROM read_parquet(%s)").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _create_table_from_parquet(
    conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, s3_path: str
) -> None:
    conn.execute(
        sql.SQL("CREATE TABLE {}.{} AS SELECT * FROM read_parquet(%s)").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
        ),
        [s3_path],
    )


def _ensure_duckgres_apply_table(conn: psycopg.Connection[Any], duckgres_schema: str) -> None:
    conn.execute(
        sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {}.{} (
                schema_id VARCHAR NOT NULL,
                run_uuid VARCHAR NOT NULL,
                batch_index BIGINT NOT NULL,
                batch_id VARCHAR NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (schema_id, run_uuid, batch_index)
            )
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        )
    )


def _has_duckgres_batch_applied(conn: psycopg.Connection[Any], duckgres_schema: str, *, batch: PendingBatch) -> bool:
    cursor = conn.execute(
        sql.SQL(
            """
            SELECT 1
            FROM {}.{}
            WHERE schema_id = %s
                AND run_uuid = %s
                AND batch_index = %s
            LIMIT 1
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        ),
        [batch.schema_id, batch.run_uuid, batch.batch_index],
    )
    return cursor.fetchone() is not None


def _mark_duckgres_batch_applied(conn: psycopg.Connection[Any], duckgres_schema: str, *, batch: PendingBatch) -> None:
    cursor = conn.execute(
        sql.SQL(
            """
            -- applied_at is set explicitly: DuckLake does not apply the column's
            -- DEFAULT now() on insert (unlike Postgres), so omitting it writes NULL
            -- and trips the NOT NULL constraint.
            INSERT INTO {}.{} (schema_id, run_uuid, batch_index, batch_id, applied_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (schema_id, run_uuid, batch_index) DO NOTHING
            """
        ).format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(DUCKGRES_APPLY_TABLE),
        ),
        [batch.schema_id, batch.run_uuid, batch.batch_index, batch.id],
    )
    if not cursor.rowcount:
        # The marker insert shares the data write's transaction, so raising here
        # rolls the data write back: the marker table is the arbiter that makes
        # concurrent double-apply impossible regardless of advisory-lock state.
        raise DuckgresBatchAlreadyAppliedError(
            f"batch {batch.schema_id}/{batch.run_uuid}/{batch.batch_index} already applied"
        )


def _prune_duckgres_apply_markers(conn: psycopg.Connection[Any], duckgres_schema: str) -> None:
    """Opportunistic retention for the duckgres-side marker table (runs at batch 0)."""
    try:
        conn.execute(
            sql.SQL("DELETE FROM {}.{} WHERE applied_at < now() - INTERVAL {}").format(
                sql.Identifier(duckgres_schema),
                sql.Identifier(DUCKGRES_APPLY_TABLE),
                sql.Literal(f"{APPLY_MARKER_RETENTION_DAYS} days"),
            )
        )
    except Exception:
        # Retention is best-effort; never fail a batch over it.
        logger.exception("duckgres_apply_marker_prune_failed", duckgres_schema=duckgres_schema)


def _read_parquet_columns(conn: psycopg.Connection[Any], s3_path: str) -> list[str]:
    return [column.name for column in _read_parquet_schema(conn, s3_path)]


def _read_parquet_schema(conn: psycopg.Connection[Any], s3_path: str) -> list[DuckgresColumn]:
    cursor = conn.execute("DESCRIBE SELECT * FROM read_parquet(%s) LIMIT 0", [s3_path])
    rows = cursor.fetchall()
    if not rows:
        raise ValueError("Duckgres could not read parquet column metadata")
    return [DuckgresColumn(name=str(row[0]), type_sql=str(row[1])) for row in rows]


def _ensure_target_columns(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    parquet_schema: list[DuckgresColumn],
) -> None:
    cursor = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
            AND table_name = %s
        """,
        [duckgres_schema, duckgres_table],
    )
    existing_columns = {str(row[0]) for row in cursor.fetchall()}

    for column in parquet_schema:
        if column.name in existing_columns:
            continue
        conn.execute(
            sql.SQL("ALTER TABLE {}.{} ADD COLUMN {} {}").format(
                sql.Identifier(duckgres_schema),
                sql.Identifier(duckgres_table),
                sql.Identifier(column.name),
                sql.SQL(column.type_sql),
            )
        )


def _apply_batch_operation(
    conn: psycopg.Connection[Any],
    operation: BatchApplyOperation,
    *,
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
) -> None:
    if operation.kind == "replace":
        _replace_table(conn, duckgres_schema, duckgres_table, s3_path)
        return
    if operation.kind == "create":
        _create_table_from_parquet(conn, duckgres_schema, duckgres_table, s3_path)
        return
    if operation.kind == "insert":
        _insert_batch(conn, duckgres_schema, duckgres_table, s3_path, columns)
        return
    if operation.kind == "merge":
        if operation.primary_keys is None:
            raise ValueError("Duckgres merge operation requires primary keys")
        _merge_batch(
            conn,
            duckgres_schema,
            duckgres_table,
            s3_path,
            columns,
            operation.primary_keys,
            operation.version_keys,
        )
        return
    raise ValueError(f"Unsupported Duckgres apply operation: {operation.kind}")


def _insert_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
) -> None:
    insert_columns = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    select_columns = sql.SQL(", ").join(sql.SQL("source.{}").format(sql.Identifier(column)) for column in columns)
    conn.execute(
        sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM read_parquet(%s) AS source").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
            insert_columns,
            select_columns,
        ),
        [s3_path],
    )


def _version_guard_clause(version_keys: list[str]) -> sql.Composed:
    """Predicate that's TRUE when the source row is at least as new as the target under the same
    `<key> DESC NULLS LAST` ordering the QUALIFY uses — i.e. a lexicographic compare of the version
    tuple. This is what keeps the no-rollback guarantee across batches (QUALIFY only acts within a
    batch), and it covers every version key, not just the terminal one, so a stale event can't
    regress an intermediate field either. Equal tuples pass through so idempotent re-delivery is a
    harmless no-op rewrite.
    """

    def newer(key: str) -> sql.Composed:
        # source.key ranks strictly ahead of target.key: a present value beats NULL (NULLS LAST),
        # and among present values a larger one is newer.
        col = sql.Identifier(key)
        return sql.SQL(
            "((target.{c} IS NULL AND source.{c} IS NOT NULL) "
            "OR (source.{c} IS NOT NULL AND target.{c} IS NOT NULL AND source.{c} > target.{c}))"
        ).format(c=col)

    def equal(key: str) -> sql.Composed:
        col = sql.Identifier(key)
        return sql.SQL("((source.{c} IS NULL AND target.{c} IS NULL) OR (source.{c} = target.{c}))").format(c=col)

    terms: list[sql.Composed] = []
    equal_prefix: list[sql.Composed] = []
    for key in version_keys:
        terms.append(sql.SQL("({})").format(sql.SQL(" AND ").join([*equal_prefix, newer(key)])))
        equal_prefix.append(equal(key))
    terms.append(sql.SQL("({})").format(sql.SQL(" AND ").join(equal_prefix)))
    return sql.SQL("({})").format(sql.SQL(" OR ").join(terms))


def _merge_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    s3_path: str,
    columns: list[str],
    primary_keys: list[str],
    version_keys: list[str] | None = None,
) -> None:
    normalized_primary_keys = [NamingConvention.normalize_identifier(key) for key in primary_keys]
    missing_keys = [key for key in normalized_primary_keys if key not in columns]
    if missing_keys:
        raise ValueError(f"Duckgres incremental batch missing primary keys: {missing_keys}")

    # A source can declare version keys an endpoint doesn't actually emit, so keep only the ones
    # present in this batch. If none survive, fall back to the legacy unordered upsert below so
    # the batch still loads rather than erroring.
    normalized_version_keys = [
        normalized
        for key in (version_keys or [])
        if (normalized := NamingConvention.normalize_identifier(key)) in columns
    ]
    missing_version_keys = [
        key for key in (version_keys or []) if NamingConvention.normalize_identifier(key) not in columns
    ]
    if missing_version_keys:
        # Any missing declared key weakens the no-rollback guard (and if all are gone, disables it).
        # A column rename would otherwise drift silently, so surface exactly which keys dropped.
        logger.warning(
            "duckgres_merge_version_keys_absent",
            duckgres_schema=duckgres_schema,
            duckgres_table=duckgres_table,
            missing_version_keys=missing_version_keys,
            declared_version_keys=version_keys,
        )

    update_columns = [column for column in columns if column not in normalized_primary_keys]
    if not update_columns:
        update_columns = [normalized_primary_keys[0]]
    on_clause = sql.SQL(" AND ").join(
        sql.SQL("source.{} = target.{}").format(sql.Identifier(key), sql.Identifier(key))
        for key in normalized_primary_keys
    )
    update_clause = sql.SQL(", ").join(
        sql.SQL("{} = source.{}").format(sql.Identifier(column), sql.Identifier(column)) for column in update_columns
    )
    insert_columns = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    insert_values = sql.SQL(", ").join(sql.SQL("source.{}").format(sql.Identifier(column)) for column in columns)

    source_relation: sql.Composable
    matched_clause: sql.Composable
    if normalized_version_keys:
        # Event-streamed sources (e.g. GitHub webhook runs/jobs) emit several rows per key —
        # queued, then in_progress, then completed. Two guards make the latest state win
        # deterministically instead of leaving it to batch/file order:
        #   1. collapse the source to the newest row per key (QUALIFY row_number), and
        #   2. only overwrite when the source row is at least as new as the target under that
        #      same ordering, so a late or out-of-order event can't roll a row back — neither
        #      its terminal field nor an intermediate one (QUALIFY only dedupes within a batch;
        #      this guard is what holds across batches).
        order_clause = sql.SQL(", ").join(
            sql.SQL("{} DESC NULLS LAST").format(sql.Identifier(key)) for key in normalized_version_keys
        )
        partition_clause = sql.SQL(", ").join(sql.Identifier(key) for key in normalized_primary_keys)
        source_relation = sql.SQL(
            "(SELECT * FROM read_parquet(%s) QUALIFY row_number() OVER (PARTITION BY {} ORDER BY {}) = 1)"
        ).format(partition_clause, order_clause)

        matched_clause = sql.SQL("WHEN MATCHED AND {guard} THEN UPDATE SET {updates}").format(
            guard=_version_guard_clause(normalized_version_keys), updates=update_clause
        )
    else:
        source_relation = sql.SQL("read_parquet(%s)")
        matched_clause = sql.SQL("WHEN MATCHED THEN UPDATE SET {}").format(update_clause)

    query = sql.SQL(
        """
        MERGE INTO {}.{} AS target
        USING {} AS source
        ON {}
        {}
        WHEN NOT MATCHED THEN INSERT ({}) VALUES ({})
        """
    ).format(
        sql.Identifier(duckgres_schema),
        sql.Identifier(duckgres_table),
        source_relation,
        on_clause,
        matched_clause,
        insert_columns,
        insert_values,
    )
    conn.execute(query, [s3_path])


def _primary_keys(batch: PendingBatch) -> list[str]:
    raw = batch.metadata.get("primary_keys")
    if not isinstance(raw, list):
        return []
    return [str(key) for key in raw]


def _version_keys(batch: PendingBatch) -> list[str] | None:
    raw = batch.metadata.get("version_keys")
    if not isinstance(raw, list):
        return None
    return [str(key) for key in raw]
