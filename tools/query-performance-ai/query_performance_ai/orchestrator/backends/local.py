"""Local-ClickHouse-backed execution.

Talks to the dev ClickHouse via the bare `clickhouse_driver.Client`. We
deliberately do NOT go through `posthog.clickhouse.client.execute.sync_execute`:
that wrapper pulls in Django + Postgres-backed team routing, query-tag thread
locals, and a bunch of plumbing that doesn't apply to a developer-local
autoresearch tool. Connection params come from `django.conf.settings` (lazy,
no app init) so we pick up the same `CLICKHOUSE_HOST`/`PASSWORD`/etc. that
the rest of the repo reads — including non-trivial defaults like
`CLICKHOUSE_SECURE = not TEST and not DEBUG` that env-var-only would miss.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from . import _query_log
from .base import BackendError, ExecutionBackend, ExecutionResult

if TYPE_CHECKING:
    from clickhouse_driver import Client

_LOCAL_DEV_DB_PROMPT = (
    "## Coordinator routing — LOCAL CLICKHOUSE MODE\n"
    "\n"
    "The coordinator is forwarding your SQL to a developer-local ClickHouse instance "
    "that contains data for **team {team_id} only**. The slow query you're optimizing was "
    "originally tagged with a different team_id; before you can capture a meaningful baseline, "
    "you MUST rewrite every team_id predicate to filter by team {team_id}.\n"
    "\n"
    "Concretely, before running the first baseline:\n"
    "1. Read `query/original.sql`.\n"
    "2. Replace every `team_id = <n>`, `team_id IN (<n>, ...)`, or any equivalent "
    "team-scoping predicate with `team_id = {team_id}`. Do this for every CTE/subquery — a "
    "missed predicate will return zero rows and silently invalidate the baseline.\n"
    "3. Save the rewritten SQL back to `query/original.sql`, `query/current.sql`, "
    "and `query/best.sql`. Then run `ch_capture_baseline.py` yourself.\n"
    "\n"
    "Do this *before* anything else. If the original SQL has no team_id predicate "
    "at all, note that in `autoresearch.md` and proceed without rewriting.\n"
)


class LocalClickhouseBackend(ExecutionBackend):
    def __init__(self, *, team_id: int = 1) -> None:
        self._team_id = team_id

    @property
    def name(self) -> str:
        return f"local-clickhouse[team={self._team_id}]"

    @property
    def target(self) -> str:
        return "local"

    def prompt_addendum(self) -> str:
        return _LOCAL_DEV_DB_PROMPT.format(team_id=self._team_id)

    def run(self, sql: str, *, timeout_s: int) -> ExecutionResult:
        # Lazy import — both clickhouse_driver and django.conf are in the
        # heavy path; keeps coordinator startup snappy when --target isn't
        # local. `django.conf.settings` is lazy and works without
        # `django.setup()`; the coordinator entry point sets
        # DJANGO_SETTINGS_MODULE so the lookup resolves to posthog.settings.
        from django.conf import settings as dj  # noqa: PLC0415

        from clickhouse_driver import Client  # noqa: PLC0415
        from clickhouse_driver.errors import Error as ClickHouseError  # noqa: PLC0415

        client = Client(
            host=dj.CLICKHOUSE_HOST,
            user=dj.CLICKHOUSE_USER,
            password=dj.CLICKHOUSE_PASSWORD,
            database=dj.CLICKHOUSE_DATABASE,
            secure=dj.CLICKHOUSE_SECURE,
            ca_certs=getattr(dj, "CLICKHOUSE_CA", None),
            verify=getattr(dj, "CLICKHOUSE_VERIFY", True),
            connect_timeout=10,
            send_receive_timeout=timeout_s + 30,
        )

        # Tag the candidate with an `autoresearch_run_id` so we can find the
        # row in `system.query_log` afterwards and pull authoritative CH-side
        # metrics (query_duration_ms / read_rows / read_bytes / query_id).
        # `client.execute` doesn't return any of those directly — and the
        # round-trip wall-clock here would bake in TLS handshake + driver
        # serialisation, so it's worth the extra lookup.
        run_id = uuid.uuid4().hex[:16]
        log_comment = json.dumps(
            {
                "product": "internal",
                "feature": "autoresearch",
                "team_id": self._team_id,
                "kind": "autoresearch_local_replay",
                "query_type": "autoresearch_candidate",
                "autoresearch_run_id": run_id,
            }
        )

        ch_settings: dict[str, Any] = {
            "max_execution_time": timeout_s,
            "max_result_rows": 10_000,
            "result_overflow_mode": "throw",
            # The slow-queries selector deliberately targets queries that
            # already OOM'd or hit memory caps; replay those without caps
            # and a faster-but-wrong candidate kills the dev CH.
            "max_memory_usage": 4 * 1024 * 1024 * 1024,  # 4 GiB
            "max_bytes_to_read": 50 * 1024 * 1024 * 1024,  # 50 GiB
            # `readonly=2` blocks DDL / DML / mutations (DROP, TRUNCATE,
            # INSERT, ALTER, OPTIMIZE) but still allows per-query SET, so
            # the other settings above keep working. The agent is an LLM
            # writing SQL; this guard means a bad rewrite can't wipe the
            # dev DB.
            "readonly": 2,
            "log_comment": log_comment,
        }

        start = time.monotonic()
        try:
            rows = client.execute(sql, settings=ch_settings, with_column_types=False)
        except ClickHouseError as e:
            client.disconnect()
            raise BackendError(f"clickhouse exec failed: {type(e).__name__}: {str(e)[:1000]}") from e
        round_trip_ms = (time.monotonic() - start) * 1000.0

        # Reuse the same connection for SYSTEM FLUSH LOGS + the query_log
        # lookup so we don't pay another TLS handshake. Failures here are
        # non-fatal — we fall back to round_trip_ms.
        try:
            log_metrics = self._fetch_query_log_metrics(client, run_id)
        finally:
            client.disconnect()

        if log_metrics is not None:
            elapsed_ms, rows_read, bytes_read, query_id = log_metrics
        else:
            elapsed_ms, rows_read, bytes_read, query_id = round_trip_ms, None, None, None

        # `Client.execute` returns `list[tuple[Any, ...]]`; normalize so the
        # JSON shape matches what MetabaseBackend produces.
        normalized = [list(row) if isinstance(row, tuple | list) else [row] for row in rows]
        return ExecutionResult(
            rows=normalized,
            elapsed_ms=elapsed_ms,
            rows_read=rows_read,
            bytes_read=bytes_read,
            query_id=query_id,
        )

    def _fetch_query_log_metrics(self, client: Client, run_id: str) -> tuple[float, int, int, str] | None:
        """Look up the candidate's row in `system.query_log` after a synchronous flush.

        ``SYSTEM FLUSH LOGS`` makes the row visible immediately on a single-node
        dev CH (the alternative — waiting for CH's ~7.5s automatic flush — is
        the metabase path because the test cluster's metabase user can't
        issue SYSTEM commands). If FLUSH LOGS fails (permissions / readonly /
        anything else) we still try the SELECT — if the row happens to be
        flushed already we'll find it; if not we return None and let the
        caller fall back to round-trip wall-clock.
        """
        from clickhouse_driver.errors import Error as ClickHouseError  # noqa: PLC0415

        sql = _query_log.build_lookup_sql(run_id, table_expr="system.query_log")
        if sql is None:
            return None
        try:
            client.execute("SYSTEM FLUSH LOGS")
        except ClickHouseError:
            pass
        try:
            rows = client.execute(sql, with_column_types=False)
        except ClickHouseError:
            return None
        if not rows:
            return None
        return _query_log.parse_lookup_row(list(rows[0]))
