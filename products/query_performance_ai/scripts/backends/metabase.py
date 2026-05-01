"""Metabase-backed execution: shell out to `hogli metabase:query`.

We reuse `hogli` for the same reason `slow_queries.py` does: cookie
handling and ALB-redirect detection live in one place, and the session
cookie never appears in this process's env or argv.
"""

from __future__ import annotations

import json
import time
import shlex
import subprocess

from .base import BackendError, ExecutionBackend, ExecutionResult

_TEAM_TWO_PROMPT = (
    "## Coordinator routing — TEST CLUSTER MODE\n"
    "\n"
    "The coordinator is forwarding your SQL to a Metabase database that contains "
    "data for **team 2 only**. The slow query you're optimizing was originally "
    "tagged with a different team_id; before you can capture a meaningful baseline, "
    "you MUST rewrite every team_id predicate to filter by team 2.\n"
    "\n"
    "Concretely, before running the first baseline:\n"
    "1. Read `query/original.sql`.\n"
    "2. Replace every `team_id = <n>`, `team_id IN (<n>, ...)`, or any equivalent "
    "team-scoping predicate with `team_id = 2`. Do this for every CTE/subquery — a "
    "missed predicate will return zero rows and silently invalidate the baseline.\n"
    "3. Save the rewritten SQL back to `query/original.sql`, `query/current.sql`, "
    "and `query/best.sql`. Then run `ch_capture_baseline.py` yourself.\n"
    "\n"
    "Do this *before* anything else. If the original SQL has no team_id predicate "
    "at all, note that in `autoresearch.md` and proceed without rewriting.\n"
)


class MetabaseBackend(ExecutionBackend):
    def __init__(self, *, region: str, database_id: int, target_label: str = "test_cluster"):
        self._region = region
        self._database_id = int(database_id)
        self._target_label = target_label

    @property
    def name(self) -> str:
        return f"metabase[{self._region}:{self._database_id}]"

    @property
    def target(self) -> str:
        return self._target_label

    def prompt_addendum(self) -> str:
        return _TEAM_TWO_PROMPT

    def run(self, sql: str, *, timeout_s: int) -> ExecutionResult:
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

        if body.get("status") == "failed" or body.get("error"):
            raise BackendError(f"metabase exec failed: {body.get('error') or body.get('status')}")

        rows = body.get("data", {}).get("rows") or []
        # Metabase reports server-side `running_time` in ms; prefer it over
        # the round-trip time so the agent's metrics aren't polluted by HTTP
        # latency.
        running_time = body.get("running_time")
        elapsed_ms = float(running_time) if isinstance(running_time, int | float) else round_trip_ms

        # Metabase doesn't surface ClickHouse's read_rows / read_bytes /
        # query_id directly. We could ask the agent to fish them out of
        # system.query_log via a follow-up query, but that doubles every
        # candidate run — leave them None and let the SKILL document the
        # query_log lookup as an explicit step when they're needed.
        return ExecutionResult(
            rows=[list(r) for r in rows],
            elapsed_ms=elapsed_ms,
            rows_read=None,
            bytes_read=None,
            query_id=None,
        )
