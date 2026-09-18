import os
from collections.abc import Sequence
from datetime import datetime

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen

from products.logs.backend.temporal.volume_tick.constants import BUCKET_SECONDS

TABLE_NAME = "logs_volume_buckets"

# Reads the physical distributed table, not `logs` — `logs` is the HogQL alias and
# does not exist for raw `sync_execute` SQL.
#
# The write, once it lands, must target the *local* replicated table instead: an
# INSERT through Distributed is async by default, so it returns before the rows
# are readable and a commit issued straight after would publish a bucket nobody
# can see. See products/analytics_platform/backend/lazy_computation/CONSISTENCY.md
# — and note that dev and CI force synchronous inserts, so that failure mode
# cannot reproduce locally.
_SOURCE_TABLE = "logs_distributed"

# `k8s.*.name` keys were never renamed, but non-Kubernetes senders carry the
# namespace in `service.namespace`, the semconv disambiguator for service.name.
_NAMESPACE_KEYS = ("k8s.namespace.name", "service.namespace")

# The one resource attribute OTel has renamed: `deployment.environment` became
# `deployment.environment.name` in semantic conventions 1.27. `env` is not a
# convention at all — it is where a Datadog `env:` tag lands, because that ingest
# path stores tags verbatim. First non-empty wins.
#
# This chain is a guess about production data. `rows_without_environment` below
# is what tests it: local fixtures cannot, because the fixtures encode the guess.
_ENVIRONMENT_KEYS = ("deployment.environment.name", "deployment.environment", "env")

# A truncated count is worse than no count: it becomes a permanent baseline the
# detector trusts, and nothing downstream can tell it apart from a real drop. So
# reads throw at the budget rather than returning what they managed to scan.
# The cap is generous against a 5-minute window and only trips on runaway volume.
_ROLLUP_QUERY_SETTINGS = {
    "max_execution_time": int(os.environ.get("LOGS_VOLUME_TICK_AGGREGATION_MAX_EXECUTION_SECONDS", "55")),
    "max_bytes_to_read": int(os.environ.get("LOGS_VOLUME_TICK_AGGREGATION_MAX_BYTES_TO_READ", str(20 * 1024**3))),
    "read_overflow_mode": "throw",
}


@frozen
class RollupPreview:
    """What one grid bucket's rollup would contain, measured without writing it."""

    rollup_rows: int
    source_rows: int
    distinct_services: int
    rows_without_namespace: int
    rows_without_environment: int


def _first_non_empty_map_key(column: str, param_prefix: str, count: int) -> str:
    """Nested `if()` over map keys, first non-empty wins, last is the fallback.

    ClickHouse Map access yields `''` for a missing key rather than NULL, so
    `coalesce` cannot express this.
    """
    expression = f"{column}[%({param_prefix}{count - 1})s]"
    for index in reversed(range(count - 1)):
        candidate = f"{column}[%({param_prefix}{index})s]"
        expression = f"if({candidate} != '', {candidate}, {expression})"
    return expression


def _rollup_sql() -> str:
    """The rollup itself: raw log rows grouped down to one row per series per bucket.

    Kept standalone so the query validated against production is the same text the
    writer will run. Turning this into the writer is an `INSERT INTO {TABLE_NAME}
    (...)` prefix plus the attempt's `generation` in the select list — the read,
    the grouping and the cost do not change.
    """
    environment = _first_non_empty_map_key("resource_attributes", "env_key_", len(_ENVIRONMENT_KEYS))
    namespace = _first_non_empty_map_key("resource_attributes", "ns_key_", len(_NAMESPACE_KEYS))
    # The grid pins UTC explicitly. Without it the bucket edges follow the session
    # timezone, so the same log would land in different buckets depending on who
    # ran the query — and bucket identity has to be stable across ticks, backfills
    # and recomputes.
    #
    # Dimensions are stored verbatim, with '' for absent. No 'unknown' sentinel:
    # it would change which rows group together, and the correctness test
    # compares these counts against a direct count of the same raw logs.
    #
    # severity_text is the exception. It is lowercased because an issue's identity
    # will include it, so a service emitting ERROR one week and error the next
    # would file two issues for one problem.
    return f"""
        SELECT
            team_id,
            toStartOfInterval(timestamp, INTERVAL %(bucket_seconds)s SECOND, 'UTC') AS time_bucket,
            service_name,
            {namespace} AS namespace,
            {environment} AS environment,
            lower(severity_text) AS severity_text,
            count() AS log_count
        FROM {_SOURCE_TABLE}
        WHERE team_id IN %(team_ids)s
            AND timestamp >= %(start)s
            AND timestamp < %(end)s
        GROUP BY team_id, time_bucket, service_name, namespace, environment, severity_text
    """


def _rollup_parameters(team_ids: Sequence[int], start: datetime, end: datetime) -> dict[str, object]:
    parameters: dict[str, object] = {
        "team_ids": list(team_ids),
        "start": start,
        "end": end,
        "bucket_seconds": BUCKET_SECONDS,
    }
    parameters.update({f"env_key_{index}": key for index, key in enumerate(_ENVIRONMENT_KEYS)})
    parameters.update({f"ns_key_{index}": key for index, key in enumerate(_NAMESPACE_KEYS)})
    return parameters


def _preview_sql() -> str:
    """Counts the rollup instead of writing it.

    The inner query is unchanged, so this reads exactly the bytes the writer will
    read and produces exactly the rows it will produce. Only the destination
    differs: five numbers to a log line and a dashboard, rather than rows to a table.
    """
    return f"""
        SELECT
            count() AS rollup_rows,
            sum(log_count) AS source_rows,
            uniqExact(service_name) AS distinct_services,
            countIf(namespace = '') AS rows_without_namespace,
            countIf(environment = '') AS rows_without_environment
        FROM ({_rollup_sql()})
    """


def preview_rollup(
    *,
    team_ids: Sequence[int],
    start: datetime,
    end: datetime,
) -> RollupPreview:
    """Measure the rollup for every grid bucket in [start, end) without writing it.

    Reads only. The two `rows_without_*` counts are the point: they say whether the
    dimensions this rollup is keyed on actually resolve against production data,
    which is the one thing that has to hold before 42 days of rows are keyed on them.

    Raises `CHQueryErrorTooManyBytes` if the scan exceeds its byte budget.
    """
    if not team_ids:
        raise ValueError("preview_rollup requires at least one team id")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError(f"start {start.isoformat()} must precede end {end.isoformat()}")
    for name, boundary in (("start", start), ("end", end)):
        if int(boundary.timestamp()) % BUCKET_SECONDS:
            raise ValueError(f"{name} {boundary.isoformat()} is not aligned to the {BUCKET_SECONDS}s grid")

    with tags_context(product=Product.LOGS, feature=Feature.PREAGGREGATION):
        rows = sync_execute(
            _preview_sql(),
            _rollup_parameters(team_ids, start, end),
            workload=Workload.LOGS,
            settings=_ROLLUP_QUERY_SETTINGS,
        )
    row = rows[0]
    return RollupPreview(
        rollup_rows=int(row[0]),
        source_rows=int(row[1]),
        distinct_services=int(row[2]),
        rows_without_namespace=int(row[3]),
        rows_without_environment=int(row[4]),
    )
