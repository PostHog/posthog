"""Metabase-backed execution: shell out to `hogli metabase:query`.

We reuse `hogli` for the same reason `slow_queries.py` does: cookie
handling and ALB-redirect detection live in one place, and the session
cookie never appears in this process's env or argv.
"""

from __future__ import annotations

import re
import json
import time
import shlex
import subprocess

from .base import BackendError, ExecutionBackend, ExecutionResult

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
        # `default` user) for cost / memory accounting. Same shape as the
        # local backend's tag so a single query_log filter sees both paths.
        log_comment = json.dumps(
            {
                "product": "internal",
                "feature": "autoresearch",
                "team_id": self._team_id,
                "kind": "autoresearch_test_cluster_replay",
                "query_type": "autoresearch_candidate",
            }
        )
        tagged_sql = _tag_with_log_comment(sql, log_comment)
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
                input=tagged_sql,
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
