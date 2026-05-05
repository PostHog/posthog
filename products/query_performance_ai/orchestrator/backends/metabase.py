"""Metabase-backed execution: shell out to `hogli metabase:query`.

We reuse `hogli` for the same reason `slow_queries.py` does: cookie
handling and ALB-redirect detection live in one place, and the session
cookie never appears in this process's env or argv.
"""

from __future__ import annotations

import re
import json
import time
import uuid
import shlex
import subprocess

from .base import BackendError, ExecutionBackend, ExecutionResult

# How long to wait for a candidate's row to appear in `system.query_log`.
# ClickHouse buffers query_log writes; the cluster's `flush_interval_milliseconds`
# is typically 7.5s (default). We poll the log up to ~9s in 1.5s steps before
# giving up and falling back to Metabase's `running_time`.
_QUERY_LOG_POLL_ATTEMPTS = 6
_QUERY_LOG_POLL_INTERVAL_S = 1.5

# Match the LAST `SETTINGS` keyword in the query so we can splice
# `log_comment = '...'` into an existing settings clause. Word-bounded and
# case-insensitive. Naive but adequate: prod query_log SQL doesn't contain
# the literal string "SETTINGS" inside string literals or comments in
# practice, and the worst case is one query getting an extra trailing
# settings clause that ClickHouse rejects with a clear parse error.
_SETTINGS_KEYWORD_RE = re.compile(r"\bSETTINGS\b", re.IGNORECASE)


def _tag_with_log_comment(sql: str, log_comment: str) -> str:
    """Inject ``SETTINGS log_comment = '...'`` into ``sql``.

    If the query already has a ``SETTINGS`` clause, merges by inserting
    ``log_comment = '<json>',`` right after the last SETTINGS keyword.
    Otherwise appends ``\\nSETTINGS log_comment = '<json>'`` after stripping
    any trailing semicolon / whitespace. The JSON is single-quote-escaped
    per ClickHouse string-literal rules (``''`` for embedded ``'``).
    """
    escaped = log_comment.replace("'", "''")
    settings_fragment = f"log_comment = '{escaped}'"

    matches = list(_SETTINGS_KEYWORD_RE.finditer(sql))
    if matches:
        # Splice into the existing SETTINGS clause. Putting log_comment first
        # is fine — ClickHouse doesn't care about settings ordering.
        last = matches[-1]
        return sql[: last.end()] + " " + settings_fragment + "," + sql[last.end() :]

    stripped = sql.rstrip().rstrip(";").rstrip()
    return f"{stripped}\nSETTINGS {settings_fragment}"


_TEST_CLUSTER_PROMPT = (
    "## Coordinator routing — TEST CLUSTER MODE\n"
    "\n"
    "The coordinator is forwarding your SQL to a Metabase database that contains "
    "data for **team {team_id} only**. The slow query you're optimizing was originally "
    "tagged with a different team_id; before you can capture a meaningful baseline, "
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


class MetabaseBackend(ExecutionBackend):
    def __init__(self, *, region: str, database_id: int, team_id: int, target_label: str = "test_cluster") -> None:
        self._region = region
        self._database_id = int(database_id)
        self._team_id = int(team_id)
        self._target_label = target_label

    @property
    def name(self) -> str:
        return f"metabase[{self._region}:{self._database_id}:team={self._team_id}]"

    @property
    def target(self) -> str:
        return self._target_label

    def prompt_addendum(self) -> str:
        return _TEST_CLUSTER_PROMPT.format(team_id=self._team_id)

    def run(self, sql: str, *, timeout_s: int) -> ExecutionResult:
        # Tag the candidate SQL with `log_comment` so `system.query_log` can
        # attribute these replays to autoresearch (and not the metabase
        # `default` user). The `autoresearch_run_id` field is what we use
        # below to find this exact run in query_log — it lets us pull the
        # authoritative ClickHouse-side metrics (query_duration_ms,
        # read_rows, read_bytes, query_id) instead of trusting Metabase's
        # `running_time` (which bakes in JDBC + JSON-serialisation overhead
        # and only reports wall-clock).
        run_id = uuid.uuid4().hex[:16]
        log_comment = json.dumps(
            {
                "product": "internal",
                "feature": "autoresearch",
                "team_id": self._team_id,
                "kind": "autoresearch_test_cluster_replay",
                "query_type": "autoresearch_candidate",
                "autoresearch_run_id": run_id,
            }
        )
        tagged_sql = _tag_with_log_comment(sql, log_comment)

        body, round_trip_ms = self._exec_via_hogli(tagged_sql, timeout_s=timeout_s)
        if body.get("status") == "failed" or body.get("error"):
            raise BackendError(f"metabase exec failed: {body.get('error') or body.get('status')}")
        rows = body.get("data", {}).get("rows") or []

        # CH-side authoritative metrics from system.query_log. None if the
        # log row hasn't flushed inside our poll budget — fall back to
        # Metabase's running_time / round-trip below.
        log_metrics = self._fetch_query_log_metrics(run_id)
        if log_metrics is not None:
            elapsed_ms, rows_read, bytes_read, query_id = log_metrics
        else:
            running_time = body.get("running_time")
            elapsed_ms = float(running_time) if isinstance(running_time, int | float) else round_trip_ms
            rows_read = None
            bytes_read = None
            query_id = None

        return ExecutionResult(
            rows=[list(r) for r in rows],
            elapsed_ms=elapsed_ms,
            rows_read=rows_read,
            bytes_read=bytes_read,
            query_id=query_id,
        )

    def _exec_via_hogli(self, sql: str, *, timeout_s: int) -> tuple[dict, float]:
        """Invoke ``hogli metabase:query`` with ``sql`` on stdin.

        Returns ``(parsed_body, round_trip_ms)``. Raises ``BackendError`` on
        any failure to communicate (timeout, non-zero exit, non-JSON body).
        Does NOT inspect ``body['status']`` / ``body['error']`` — the caller
        decides whether a CH-side failure should propagate or be tolerated
        (the query_log lookup tolerates "no results yet" as a poll miss).
        """
        cmd = [
            "hogli",
            "metabase:query",
            "--region",
            self._region,
            "--database-id",
            str(self._database_id),
            "--format",
            "json",
            "--timeout",
            str(timeout_s),
        ]
        start = time.monotonic()
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, sql via stdin
                cmd,
                input=sql,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_s + 30,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"metabase request timed out after {e.timeout}s") from e
        round_trip_ms = (time.monotonic() - start) * 1000.0

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            # `hogli metabase:query` exits non-zero with a `Query failed: …`
            # ClickException for backend-side failures (auth, CH error). The
            # message is safe to surface — it's already what a human would see
            # at the CLI.
            raise BackendError(f"metabase exec failed: {stderr[:1000] or shlex.join(cmd)}")

        try:
            body = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(f"metabase returned non-JSON response: {result.stdout[:500]!r}") from e
        return body, round_trip_ms

    def _fetch_query_log_metrics(self, run_id: str) -> tuple[float, int, int, str] | None:
        """Poll `system.query_log` for the row matching ``autoresearch_run_id``.

        Returns ``(query_duration_ms, read_rows, read_bytes, query_id)`` once
        the row has flushed, or ``None`` if the poll budget elapses without a
        match. ``run_id`` is hex-only (``uuid.hex[:16]``) so it's safe to
        interpolate into the SQL string-literal directly.
        """
        # Defence-in-depth: refuse anything that isn't 16 hex chars.
        if not re.fullmatch(r"[0-9a-f]{16}", run_id):
            return None
        sql = (
            "SELECT query_duration_ms, read_rows, read_bytes, query_id "
            "FROM clusterAllReplicas(posthog, system, query_log) "
            "WHERE event_date >= today() - 1 "
            "AND type = 'QueryFinish' "
            f"AND JSONExtractString(log_comment, 'autoresearch_run_id') = '{run_id}' "
            "ORDER BY event_time DESC LIMIT 1"
        )
        for attempt in range(_QUERY_LOG_POLL_ATTEMPTS):
            if attempt > 0:
                time.sleep(_QUERY_LOG_POLL_INTERVAL_S)
            try:
                body, _ = self._exec_via_hogli(sql, timeout_s=15)
            except BackendError:
                return None
            if body.get("status") == "failed" or body.get("error"):
                return None
            rows = body.get("data", {}).get("rows") or []
            if rows:
                duration_ms, rows_read, bytes_read, query_id = rows[0]
                return float(duration_ms), int(rows_read), int(bytes_read), str(query_id)
        return None
