from __future__ import annotations

import time
import atexit
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import sleep as _real_sleep  # captured before any test patches this module's `time`
from typing import Any, Literal
from weakref import WeakKeyDictionary

from django.conf import settings
from django.db import close_old_connections

import psycopg
import structlog
from prometheus_client import Histogram
from psycopg import sql

from posthog.ducklake.common import duckgres_data_imports_schema, get_duckgres_config_for_org
from posthog.ducklake.storage import setup_duckgres_session
from posthog.models import Team

from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    PermanentBatchApplyError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import batch_kind
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

# Per-batch apply latency, split by phase and kind. Fine buckets on purpose: the
# shared engine histogram (batch_processing_duration_seconds) floors at 0.5s, so
# this is the only place sub-second live-apply latency and the backfill phase
# breakdown (schema_read vs data_load vs swap) are observable.
_PHASE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)

APPLY_PHASE_DURATION_SECONDS = Histogram(
    "duckgres_sink_apply_phase_duration_seconds",
    "Duckgres sink per-batch apply latency by phase (connect_setup, schema_read, data_load/apply, swap) and kind (live/backfill)",
    labelnames=["phase", "kind"],
    buckets=_PHASE_BUCKETS,
)

BACKFILL_CHUNK_FILES = Histogram(
    "duckgres_sink_backfill_chunk_files",
    "Source parquet files per backfill chunk — drives read_parquet/union_by_name footer-read cost",
    buckets=(1, 2, 5, 10, 25, 50, 100, 200, 350, 512),
)


def _record_phase(phase: str, kind: str, elapsed: float, acc: dict[str, float]) -> None:
    """Observe a phase's wall time on the histogram and record it (ms) into ``acc`` for logging."""
    APPLY_PHASE_DURATION_SECONDS.labels(phase=phase, kind=kind).observe(elapsed)
    acc[phase] = round(elapsed * 1000, 1)


@contextmanager
def _timed(phase: str, kind: str, acc: dict[str, float]) -> Iterator[None]:
    """Time a block and record the phase even if it raises (mirrors error-path capture)."""
    start = time.monotonic()
    try:
        yield
    finally:
        _record_phase(phase, kind, time.monotonic() - start, acc)


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


class _DuckgresSessionCache:
    """Reuse one duckgres connection across consecutive live batches of a group.

    The dominant per-batch costs measured in prod (2026-07-22) are per-SESSION
    fixed costs, not row volume: worker session create (~0.5-1s), the extended-
    protocol describe probe's cold catalog enumeration (~5-19s), and the
    transaction's first-write metadata touch on the target table (~12-19s).
    All are warm on a reused session, taking a live batch from ~30-40s to ~2s.

    Keyed by (org_id, team_id, schema_id): the sink's group lease serializes
    each (team, schema) to one pod task at a time, so entries are never used
    concurrently — the lock guards only the dict. The org is part of the key
    so a team transferred between organizations can never keep writing through
    the previous org's authenticated connection. Entries are dropped on any
    processing error (the connection may hold aborted-transaction state), after
    IDLE_TTL without reuse, and past MAX_AGE outright (the extract-read secret
    embeds session credentials that expire; a fresh session re-mints them).
    A daemon sweeper enforces both bounds independently of traffic — without
    it, a drained group's session would pin its duckgres worker (one session
    per worker) indefinitely, outside the sink's org connection budget; with
    it, the pin is bounded by IDLE_TTL + SWEEP_INTERVAL. atexit clears the
    cache on graceful shutdown.
    """

    IDLE_TTL_SECONDS = 90.0
    MAX_AGE_SECONDS = 600.0
    SWEEP_INTERVAL_SECONDS = 30.0
    # Retained sessions pin duckgres workers, so cap them per org: even a burst
    # of sequentially drained groups can never hold more than this many of an
    # org's connections beyond its active leases (per consumer pod).
    MAX_SESSIONS_PER_ORG = 4

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, int, str], tuple[psycopg.Connection[Any], float, float]] = {}
        self._sweeper_started = False

    def acquire(self, org_id: str, team_id: int, schema_id: str) -> tuple[psycopg.Connection[Any] | None, float]:
        """Return (connection, session_created_at); (None, now) means connect fresh.

        created_at is threaded back through store() so the MAX_AGE credential
        cap tracks the ORIGINAL session creation across any number of reuses.
        """
        key = (org_id, team_id, schema_id)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.pop(key, None)
        if entry is None:
            return None, now
        conn, created_at, last_used = entry
        if now - last_used > self.IDLE_TTL_SECONDS or now - created_at > self.MAX_AGE_SECONDS:
            self._close_quietly(conn)
            return None, now
        return conn, created_at

    def store(
        self, org_id: str, team_id: int, schema_id: str, conn: psycopg.Connection[Any], created_at: float
    ) -> None:
        self._ensure_sweeper()
        key = (org_id, team_id, schema_id)
        overflow = []
        with self._lock:
            previous = self._entries.get(key)
            self._entries[key] = (conn, created_at, time.monotonic())
            org_keys = [k for k in self._entries if k[0] == org_id]
            if len(org_keys) > self.MAX_SESSIONS_PER_ORG:
                org_keys.sort(key=lambda k: self._entries[k][2])  # oldest last-use first
                for stale_key in org_keys[: len(org_keys) - self.MAX_SESSIONS_PER_ORG]:
                    overflow.append(self._entries.pop(stale_key))
        if previous is not None and previous[0] is not conn:
            self._close_quietly(previous[0])
        for other_conn, _, _ in overflow:
            self._close_quietly(other_conn)

    def _ensure_sweeper(self) -> None:
        # Lazy start: this module is imported by processes that never run the
        # sink; only a process that actually caches a session gets the thread.
        with self._lock:
            if self._sweeper_started:
                return
            self._sweeper_started = True
        threading.Thread(target=self._sweep_loop, daemon=True, name="duckgres-session-cache-sweeper").start()

    def _sweep_loop(self) -> None:
        while True:
            _real_sleep(self.SWEEP_INTERVAL_SECONDS)
            try:
                self._evict_stale()
            except Exception:
                pass

    def _evict_stale(self) -> None:
        """Close entries past either bound — runs on the sweeper, not on traffic."""
        now = time.monotonic()
        with self._lock:
            stale = [
                k
                for k, (_, created_at, used) in self._entries.items()
                if now - used > self.IDLE_TTL_SECONDS or now - created_at > self.MAX_AGE_SECONDS
            ]
            evicted = [self._entries.pop(k) for k in stale]
        for conn, _, _ in evicted:
            self._close_quietly(conn)

    def clear(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for conn, _, _ in entries:
            self._close_quietly(conn)

    @staticmethod
    def _close_quietly(conn: psycopg.Connection[Any]) -> None:
        try:
            conn.close()
        except Exception:
            pass


_session_cache = _DuckgresSessionCache()
atexit.register(_session_cache.clear)


def process_batch(batch: PendingBatch) -> None:
    # Threads are reused across batches; drop stale app-DB connections so the ORM
    # reads below reconnect instead of failing every attempt after a DB bounce.
    close_old_connections()

    schema: ExternalDataSchema
    if _is_backfill_batch(batch):
        # Synthetic backfill batches carry a sentinel job_id; resolve the schema
        # directly instead of via ExternalDataJob.
        schema = ExternalDataSchema.objects.select_related("source").get(
            id=batch.schema_id,
            team_id=batch.team_id,
        )
    else:
        job = ExternalDataJob.objects.select_related("schema", "schema__source").get(
            id=batch.job_id,
            team_id=batch.team_id,
        )
        if job.schema is None:
            raise ValueError(f"ExternalDataJob {batch.job_id} has no schema")
        schema = job.schema

    kind = "backfill" if _is_backfill_batch(batch) else "live"
    # One ORM lookup serves both the cache key and the connection config; it is
    # per-batch on purpose so the key always reflects the team's CURRENT org.
    org_id = str(Team.objects.only("organization_id").get(id=batch.team_id).organization_id)
    timings: dict[str, float] = {}
    # Connect + session + secret is a fixed cost; measured as one phase so the
    # connection-reuse win is visible against the apply itself (a cache hit
    # records ~0). Recorded in a finally so a slow/failing connect (e.g.
    # cold-tenant activation timeout) still lands in the phase metric.
    connect_start = time.monotonic()
    if kind == "backfill":
        # Backfills are rare, long, and chunk-coalesced already — keep the
        # simple fresh-connection lifecycle.
        try:
            with _connect_to_duckgres(org_id) as conn:
                # The sink only reads parquet over S3; httpfs is bundled in the duckgres
                # worker image so INSTALL is a local no-op. Do NOT add extensions that are
                # not bundled (e.g. delta): egress-restricted workers silently drop the
                # CDN download and the statement hangs.
                setup_duckgres_session(conn, extensions=("httpfs",))
                _create_extract_read_secret(conn)
                _record_phase("connect_setup", kind, time.monotonic() - connect_start, timings)
                try:
                    _process_backfill_batch(conn, batch, schema, timings=timings)
                except DuckgresBatchAlreadyAppliedError:
                    _log_applied_by_concurrent_processor(batch)
        finally:
            if "connect_setup" not in timings:
                _record_phase("connect_setup", kind, time.monotonic() - connect_start, timings)
        return

    # Distinct name from the backfill branch's `with ... as conn` binding: this
    # one is Optional until the cache miss connects, and mypy types by first use.
    session_conn, session_created_at = _session_cache.acquire(org_id, batch.team_id, batch.schema_id)
    try:
        if session_conn is None:
            session_conn = _connect_to_duckgres(org_id)
            setup_duckgres_session(session_conn, extensions=("httpfs",))
            _create_extract_read_secret(session_conn)
        _record_phase("connect_setup", kind, time.monotonic() - connect_start, timings)
        try:
            _process_batch(session_conn, batch, schema, timings=timings)
        except DuckgresBatchAlreadyAppliedError:
            _log_applied_by_concurrent_processor(batch)
    except BaseException:
        # The connection may hold aborted-transaction or half-streamed state;
        # never cache it. The queue's retry gets a fresh session.
        if session_conn is not None:
            _DuckgresSessionCache._close_quietly(session_conn)
        raise
    else:
        _session_cache.store(org_id, batch.team_id, batch.schema_id, session_conn, created_at=session_created_at)
    finally:
        if "connect_setup" not in timings:
            _record_phase("connect_setup", kind, time.monotonic() - connect_start, timings)


def _log_applied_by_concurrent_processor(batch: PendingBatch) -> None:
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


def _connect_to_duckgres(org_id: str) -> psycopg.Connection[Any]:
    config = get_duckgres_config_for_org(org_id)
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


def _is_backfill_batch(batch: PendingBatch) -> bool:
    return batch_kind.is_backfill_metadata(batch.metadata)


def _backfill_chunk_paths(batch: PendingBatch) -> list[str]:
    try:
        return batch_kind.backfill_chunk_paths(batch.metadata)
    except ValueError as e:
        # Falling back to s3_path would silently apply only the chunk's first
        # file; a malformed synthetic row must fail loudly instead.
        raise PermanentBatchApplyError(f"backfill batch {batch.id}: {e}") from e


def _read_parquet_expr(paths: list[str], *, union_by_name: bool = False) -> sql.Composable:
    """read_parquet([...]) with inlined literals — list parameters do not bind
    reliably over the duckgres extended protocol. union_by_name aligns
    schema-evolved files within one chunk by column name (backfill chunks span
    months of Delta writes; positional unification fails on added columns)."""
    opts = sql.SQL(", union_by_name=true") if union_by_name else sql.SQL("")
    return sql.SQL("read_parquet([{}]{})").format(
        sql.SQL(", ").join(sql.Literal(p) for p in paths),
        opts,
    )


def _backfill_table_name(live_table: str, schema_id: str) -> str:
    # Suffix with a schema-id fragment: pure prefix truncation could collide
    # for two schemas sharing a long name prefix in the same team schema.
    return f"{live_table[:42]}__bf_{schema_id.replace('-', '')[:8]}"


def _process_batch(
    conn: psycopg.Connection[Any],
    batch: PendingBatch,
    schema: ExternalDataSchema,
    timings: dict[str, float] | None = None,
) -> None:
    timings = timings if timings is not None else {}
    duckgres_schema = _duckgres_schema_name(batch.team_id)
    duckgres_table = _duckgres_table_name(schema)

    conn.execute(
        sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(duckgres_schema)),
    )

    if batch.sync_type == "cdc":
        raise PermanentBatchApplyError("Duckgres batch sink does not support CDC batches yet")

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

    with _timed("schema_read", "live", timings):
        parquet_schema = _read_parquet_schema(conn, [batch.s3_path])
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

    with _timed("apply", "live", timings), conn.transaction():
        if operation.ensure_target_columns:
            _ensure_target_columns(conn, duckgres_schema, duckgres_table, parquet_schema)
        _apply_batch_operation(
            conn,
            operation,
            duckgres_schema=duckgres_schema,
            duckgres_table=duckgres_table,
            paths=[batch.s3_path],
            columns=columns,
        )
        _mark_duckgres_batch_applied(conn, duckgres_schema, batch=batch)
        return


def _process_backfill_batch(
    conn: psycopg.Connection[Any],
    batch: PendingBatch,
    schema: ExternalDataSchema,
    timings: dict[str, float] | None = None,
) -> None:
    """Apply one backfill chunk into <table>__backfill; the last chunk swaps it live.

    See BACKFILL_SPEC.md. The swap (DROP live + RENAME) shares the last chunk's
    transaction together with the apply-marker arbiter, so it is atomic and
    exactly-once even with a concurrent processor.
    """
    timings = timings if timings is not None else {}
    duckgres_schema = _duckgres_schema_name(batch.team_id)
    live_table = _duckgres_table_name(schema)
    backfill_table = _backfill_table_name(live_table, batch.schema_id)
    chunk_count = batch_kind.backfill_chunk_count(batch.metadata)
    is_last = chunk_count > 0 and batch.batch_index == chunk_count - 1

    conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(duckgres_schema)))
    _ensure_duckgres_apply_table(conn, duckgres_schema)

    if _has_duckgres_batch_applied(conn, duckgres_schema, batch=batch):
        logger.info(
            "duckgres_backfill_chunk_already_applied",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            run_uuid=batch.run_uuid,
            batch_index=batch.batch_index,
        )
        if is_last:
            # Crash between the swap's commit and the state flip lands here on
            # retry: the swap is proven (the marker shared its transaction),
            # only the app-DB flip is missing. Idempotent via CAS.
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill import (
                mark_primed,
            )

            mark_primed(batch.schema_id, run_uuid=batch.run_uuid, chunks_applied=chunk_count)
        return

    chunk_paths = _backfill_chunk_paths(batch)
    BACKFILL_CHUNK_FILES.observe(len(chunk_paths))
    with _timed("schema_read", "backfill", timings):
        parquet_schema = _read_parquet_schema(conn, chunk_paths, union_by_name=True)
    columns = [column.name for column in parquet_schema]

    with conn.transaction():
        with _timed("data_load", "backfill", timings):
            if batch.batch_index == 0:
                # CREATE OR REPLACE makes a re-planned backfill self-cleaning.
                conn.execute(
                    sql.SQL("CREATE OR REPLACE TABLE {}.{} AS SELECT * FROM {}").format(
                        sql.Identifier(duckgres_schema),
                        sql.Identifier(backfill_table),
                        _read_parquet_expr(chunk_paths, union_by_name=True),
                    )
                )
            else:
                _ensure_target_columns(conn, duckgres_schema, backfill_table, parquet_schema)
                _insert_batch(conn, duckgres_schema, backfill_table, chunk_paths, columns, union_by_name=True)

        if is_last:
            logger.info(
                "duckgres_backfill_swapping",
                team_id=batch.team_id,
                schema_id=batch.schema_id,
                run_uuid=batch.run_uuid,
                table=live_table,
                chunk_count=chunk_count,
            )
            with _timed("swap", "backfill", timings):
                conn.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                        sql.Identifier(duckgres_schema), sql.Identifier(live_table)
                    )
                )
                conn.execute(
                    sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                        sql.Identifier(duckgres_schema),
                        sql.Identifier(backfill_table),
                        sql.Identifier(live_table),
                    )
                )

        _mark_duckgres_batch_applied(conn, duckgres_schema, batch=batch)

    logger.info(
        "duckgres_backfill_chunk_timing",
        team_id=batch.team_id,
        schema_id=batch.schema_id,
        run_uuid=batch.run_uuid,
        batch_index=batch.batch_index,
        chunk_count=chunk_count,
        is_last=is_last,
        file_count=len(chunk_paths),
        connect_setup_ms=timings.get("connect_setup"),
        schema_read_ms=timings.get("schema_read"),
        data_load_ms=timings.get("data_load"),
        swap_ms=timings.get("swap"),
    )

    if is_last:
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill import (
            mark_primed,
        )

        mark_primed(batch.schema_id, run_uuid=batch.run_uuid, chunks_applied=chunk_count)
        logger.info(
            "duckgres_backfill_swapped",
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            table=live_table,
        )


def _duckgres_schema_name(team_id: int) -> str:
    # Resolves to posthog_data_imports_<table_suffix> when the team has set one
    # (DuckgresServerTeam.table_suffix — the same suffix that names its
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
            raise PermanentBatchApplyError("Duckgres incremental batches require primary keys")
        return BatchApplyOperation(kind="merge", ensure_target_columns=True, primary_keys=primary_keys)

    if batch.sync_type in ("full_refresh", "append"):
        return BatchApplyOperation(kind="insert", ensure_target_columns=True)

    raise PermanentBatchApplyError(f"Unsupported Duckgres sync type: {batch.sync_type}")


# Per-connection cache of tables confirmed to exist: the sink checks existence
# every non-first batch, so cache positive results (a table stays existing for
# the connection's life — the sink never drops tables mid-run). Only positives
# are cached (a table may be created between batches); GC'd with the connection.
_existing_tables: WeakKeyDictionary[psycopg.Connection[Any], set[tuple[str, str]]] = WeakKeyDictionary()


def _table_exists(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str) -> bool:
    known = _existing_tables.setdefault(conn, set())
    if (duckgres_schema, duckgres_table) in known:
        return True
    exists = _probe_table_exists(conn, duckgres_schema, duckgres_table)
    if exists:
        known.add((duckgres_schema, duckgres_table))
    return exists


def _probe_table_exists(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str) -> bool:
    """Cheap single-table existence probe (autocommit, so a raised error is inert).

    A `LIMIT 0` reference loads only this table's metadata (~0.1-0.6s even under
    concurrent snapshot commits); the former `information_schema.tables` check
    re-materialized the whole catalog (~48s under load on a large catalog).
    duckgres reports a missing table as a generic XX000 carrying DuckDB's stable
    "Table with name X does not exist" catalog message. Match that specifically —
    a bare "does not exist" would also swallow a missing schema/catalog/secret,
    wrongly routing a real failure to the create path. Anything else propagates.
    """
    try:
        conn.execute(
            sql.SQL("SELECT 1 FROM {}.{} LIMIT 0").format(
                sql.Identifier(duckgres_schema), sql.Identifier(duckgres_table)
            )
        )
        return True
    except psycopg.Error as err:
        message = str(err).lower()
        if "table with name" in message and "does not exist" in message:
            return False
        raise


def _replace_table(conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, paths: list[str]) -> None:
    conn.execute(
        sql.SQL("CREATE OR REPLACE TABLE {}.{} AS SELECT * FROM {}").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
            _read_parquet_expr(paths),
        )
    )


def _create_table_from_parquet(
    conn: psycopg.Connection[Any], duckgres_schema: str, duckgres_table: str, paths: list[str]
) -> None:
    conn.execute(
        sql.SQL("CREATE TABLE {}.{} AS SELECT * FROM {}").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
            _read_parquet_expr(paths),
        )
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


def _read_parquet_columns(conn: psycopg.Connection[Any], paths: list[str]) -> list[str]:
    return [column.name for column in _read_parquet_schema(conn, paths)]


def _read_parquet_schema(
    conn: psycopg.Connection[Any], paths: list[str], *, union_by_name: bool = False
) -> list[DuckgresColumn]:
    cursor = conn.execute(
        sql.SQL("DESCRIBE SELECT * FROM {} LIMIT 0").format(_read_parquet_expr(paths, union_by_name=union_by_name))
    )
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
    paths: list[str],
    columns: list[str],
) -> None:
    if operation.kind == "replace":
        _replace_table(conn, duckgres_schema, duckgres_table, paths)
        return
    if operation.kind == "create":
        _create_table_from_parquet(conn, duckgres_schema, duckgres_table, paths)
        return
    if operation.kind == "insert":
        _insert_batch(conn, duckgres_schema, duckgres_table, paths, columns)
        return
    if operation.kind == "merge":
        if operation.primary_keys is None:
            raise PermanentBatchApplyError("Duckgres merge operation requires primary keys")
        _merge_batch(conn, duckgres_schema, duckgres_table, paths, columns, operation.primary_keys)
        return
    raise PermanentBatchApplyError(f"Unsupported Duckgres apply operation: {operation.kind}")


def _insert_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    paths: list[str],
    columns: list[str],
    *,
    union_by_name: bool = False,
) -> None:
    insert_columns = sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    select_columns = sql.SQL(", ").join(sql.SQL("source.{}").format(sql.Identifier(column)) for column in columns)
    conn.execute(
        sql.SQL("INSERT INTO {}.{} ({}) SELECT {} FROM {} AS source").format(
            sql.Identifier(duckgres_schema),
            sql.Identifier(duckgres_table),
            insert_columns,
            select_columns,
            _read_parquet_expr(paths, union_by_name=union_by_name),
        )
    )


def _merge_batch(
    conn: psycopg.Connection[Any],
    duckgres_schema: str,
    duckgres_table: str,
    paths: list[str],
    columns: list[str],
    primary_keys: list[str],
) -> None:
    normalized_primary_keys = [NamingConvention.normalize_identifier(key) for key in primary_keys]
    missing_keys = [key for key in normalized_primary_keys if key not in columns]
    if missing_keys:
        raise PermanentBatchApplyError(f"Duckgres incremental batch missing primary keys: {missing_keys}")

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
        _read_parquet_expr(paths),
        on_clause,
        matched_clause,
        insert_columns,
        insert_values,
    )
    conn.execute(query)


def _primary_keys(batch: PendingBatch) -> list[str]:
    raw = batch.metadata.get("primary_keys")
    if not isinstance(raw, list):
        return []
    return [str(key) for key in raw]
