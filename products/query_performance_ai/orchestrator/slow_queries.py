"""Source slow queries from Metabase's view of `system.query_log`.

We always source via Metabase regardless of where the coordinator runs the
agent's candidate queries — the `ai_data_processing_approved` tag only
exists in production query_log, and that's the only thing standing
between us and replaying SQL we don't have permission to replay.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass

# All filters from the human's reference query, minus the snippet macros and
# decorative columns. We only need: raw SQL, duration, bytes, query_id,
# team_id, event_time. Filtering ai_data_processing_approved = 'true' is
# load-bearing — do not relax it.
_SLOW_QUERIES_SQL = """
SELECT
    query_id,
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    -- The actual rendered ClickHouse SQL that ran. This is what we hand to the
    -- campaign — the metabase / local-CH backends both speak ClickHouse SQL,
    -- not HogQL.
    query AS clickhouse_query,
    -- The HogQL JSON envelope kept for context only (some campaigns may want
    -- to reason about the higher-level query intent).
    JSONExtractString(log_comment, 'query') AS hogql_query,
    query_duration_ms,
    read_bytes,
    -- Aliasing the formatted string back to `event_time` collides with the
    -- DateTime column the WHERE clause uses; pick a distinct alias.
    toString(event_time) AS event_time_iso
FROM clusterAllReplicas(posthog, system, query_log)
WHERE
    event_time > now() - INTERVAL {lookback_hours} HOUR
    AND JSONExtractInt(log_comment, 'team_id') = {team_id}
    AND JSONExtractString(log_comment, 'workload') NOT IN ('Workload.OFFLINE', 'OFFLINE')
    AND JSONExtractString(log_comment, 'kind') NOT IN ('temporal')
    AND JSONExtractString(log_comment, 'access_method') NOT IN ('personal_api_key')
    AND is_initial_query
    AND (query_duration_ms > 30000 OR exception_code IN (159, 160, 241))
    AND JSONExtractString(log_comment, 'ai_data_processing_approved') = 'true'
    AND notEmpty(JSONExtractString(log_comment, 'query'))
    {column_filter_clause}
ORDER BY query_duration_ms DESC
LIMIT {limit}
"""

# When we know which columns the execution target has, drop queries that
# reference a column NAME (not table) the target lacks — saves the agent
# the wild-goose repair attempts we saw on materialized columns missing
# from the test cluster. We compare on column name only because
# prod-vs-test-cluster table names diverge (e.g. `sharded_events` on prod
# is exposed as `events` on the test cluster's metabase database).
# `system.query_log.columns` entries are formatted `database.table.column`
# with backticks around any column whose name needs quoting (e.g.
# `mat_$host`); strip the prefix and the backticks before comparing.
_COLUMN_FILTER_CLAUSE = (
    "AND hasAll({available!r}, arrayDistinct(arrayMap(c -> replaceAll(splitByChar('.', c)[3], '`', ''), columns)))"
)

# Same idea as the column filter, but for ClickHouse dictionaries (referenced via
# dictGet*/dictHas etc.). `system.query_log.used_dictionaries` is already in
# `database.name` form, so we compare directly without splitting.
_DICTIONARY_FILTER_CLAUSE = "AND hasAll({available!r}, used_dictionaries)"


@dataclass(frozen=True)
class SlowQuery:
    query_id: str
    team_id: int
    # Rendered ClickHouse SQL exactly as it ran on the cluster — what we hand
    # to the campaign as `CAMPAIGN_SQL`.
    clickhouse_query: str
    # The HogQL JSON envelope (from log_comment.query). Useful as context but
    # not directly executable on the test cluster — it references HogQL
    # abstractions like saved-query views that don't exist as CH tables.
    hogql_query: str
    query_duration_ms: int
    read_bytes: int
    event_time: str


def build_sql(
    *,
    team_id: int,
    lookback_hours: int,
    limit: int,
    available_columns: list[str] | None = None,
    available_dictionaries: list[str] | None = None,
) -> str:
    """Public for tests — keeps the formatting check trivial.

    When ``available_columns`` is provided, restricts results to queries that
    only reference columns in the list. When ``available_dictionaries`` is
    provided (entries in the form ``database.dict_name`` to match
    ``system.query_log.used_dictionaries``), restricts to queries that only
    use dictionaries in the list — pass an empty list ``[]`` to require zero
    dictionary use. Pass ``None`` to skip either filter.
    """
    clauses: list[str] = []
    if available_columns:
        clauses.append(_COLUMN_FILTER_CLAUSE.format(available=sorted(available_columns)))
    if available_dictionaries is not None:
        clauses.append(_DICTIONARY_FILTER_CLAUSE.format(available=sorted(available_dictionaries)))
    return _SLOW_QUERIES_SQL.format(
        lookback_hours=int(lookback_hours),
        team_id=int(team_id),
        limit=int(limit),
        column_filter_clause="\n    ".join(clauses),
    )


def fetch_slow_queries(
    *,
    region: str,
    database_id: int,
    team_id: int,
    lookback_hours: int = 24,
    limit: int = 10,
    timeout_s: float = 90.0,
    available_columns: list[str] | None = None,
    available_dictionaries: list[str] | None = None,
) -> list[SlowQuery]:
    """Run the slow-queries SQL via `hogli metabase:query` and parse the rows.

    We shell out to `hogli` rather than re-implementing cookie handling
    here — the cookie cache, ALB redirect detection, and SSO refresh
    instructions all live in one place that way, and the cookie value
    never lands in this process's argv or env.
    """
    sql = build_sql(
        team_id=team_id,
        lookback_hours=lookback_hours,
        limit=limit,
        available_columns=available_columns,
        available_dictionaries=available_dictionaries,
    )
    cmd = [
        "hogli",
        "metabase:query",
        "--region",
        region,
        "--database-id",
        str(database_id),
        "--format",
        "json",
        "--timeout",
        str(timeout_s),
    ]
    result = subprocess.run(  # noqa: S603 — fixed argv, sql via stdin
        cmd,
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_s + 30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"hogli metabase:query failed (exit {result.returncode}):\n"
            f"  cmd: {shlex.join(cmd)}\n"
            f"  stderr: {(result.stderr or '').strip()[:1000]}"
        )

    return parse_metabase_response(result.stdout)


# The user-facing tables most slow queries actually reference. We
# scope the column filter to these because the test cluster's underlying
# `sharded_events*` tables have a richer schema than its `events`
# Distributed wrapper, and the filter has to match what the query
# resolves through, not the union of every table in the database.
_USER_FACING_TABLES = ("events", "person", "raw_sessions")


def fetch_available_columns(
    *,
    region: str,
    database_id: int,
    tables: tuple[str, ...] = _USER_FACING_TABLES,
    timeout_s: float = 60.0,
) -> list[str]:
    """Return the *set of column NAMES* the metabase database exposes on the
    ``posthog.<table>`` for each of ``tables``.

    Used to pre-filter the slow-queries query so we never hand the agent a
    campaign that's blocked on a materialized column the test cluster doesn't
    have. We return names rather than ``database.table.column`` triples
    because prod and the test cluster use different physical tables for the
    same logical thing (e.g. prod's queries record `sharded_events.foo` in
    query_log but the test cluster's `events` Distributed table is the
    actual backing target). Scoping to ``events``/``person``/``raw_sessions``
    matches what user-facing queries actually go through.
    """
    table_list = ", ".join(f"'{t}'" for t in tables)
    sql = f"SELECT DISTINCT name FROM system.columns WHERE database = 'posthog' AND table IN ({table_list})"
    cmd = [
        "hogli",
        "metabase:query",
        "--region",
        region,
        "--database-id",
        str(database_id),
        "--format",
        "json",
        "--timeout",
        str(timeout_s),
    ]
    result = subprocess.run(  # noqa: S603 — fixed argv, sql via stdin
        cmd,
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_s + 30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"hogli metabase:query failed (exit {result.returncode}):\n  stderr: {(result.stderr or '').strip()[:500]}"
        )
    body = json.loads(result.stdout)
    return [name for (name,) in body["data"]["rows"]]


def fetch_available_dictionaries(*, region: str, database_id: int, timeout_s: float = 60.0) -> list[str]:
    """Return ``database.name`` for each ClickHouse dictionary on the test cluster.

    Format matches ``system.query_log.used_dictionaries`` so we can pass the
    result straight into the slow-queries dictionary filter. An empty list
    means the test cluster has no dictionaries — we'll filter out every
    query that uses one.
    """
    sql = "SELECT database, name FROM system.dictionaries WHERE database = 'posthog'"
    cmd = [
        "hogli",
        "metabase:query",
        "--region",
        region,
        "--database-id",
        str(database_id),
        "--format",
        "json",
        "--timeout",
        str(timeout_s),
    ]
    result = subprocess.run(  # noqa: S603 — fixed argv, sql via stdin
        cmd,
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_s + 30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"hogli metabase:query failed (exit {result.returncode}):\n  stderr: {(result.stderr or '').strip()[:500]}"
        )
    body = json.loads(result.stdout)
    return [f"{db}.{name}" for db, name in body["data"]["rows"]]


def parse_metabase_response(raw: str) -> list[SlowQuery]:
    body = json.loads(raw)
    cols = [c["name"] for c in body["data"]["cols"]]
    out: list[SlowQuery] = []
    for row in body["data"]["rows"]:
        record = dict(zip(cols, row))
        out.append(
            SlowQuery(
                query_id=str(record["query_id"]),
                team_id=int(record["team_id"]),
                clickhouse_query=str(record["clickhouse_query"]),
                hogql_query=str(record["hogql_query"]),
                query_duration_ms=int(record["query_duration_ms"]),
                read_bytes=int(record["read_bytes"]),
                event_time=str(record["event_time_iso"]),
            )
        )
    return out
