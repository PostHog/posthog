import os
from collections.abc import Sequence
from datetime import datetime

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen

from products.logs.backend.temporal.volume_tick.constants import BUCKET_SECONDS

TABLE_NAME = "logs_volume_buckets"

# Writes target the local replicated table, not the distributed alias. An INSERT
# through Distributed is async by default, so it returns before the rows are
# readable and a commit issued straight after would publish a bucket nobody can
# see. See products/analytics_platform/backend/lazy_computation/CONSISTENCY.md —
# note that dev and CI force synchronous inserts, so this failure mode cannot
# reproduce locally.
_SOURCE_TABLE = "logs_distributed"

# `k8s.*.name` keys were never renamed, so namespace needs no fallback.
_NAMESPACE_KEY = "k8s.namespace.name"

# The one resource attribute OTel has renamed: `deployment.environment` became
# `deployment.environment.name` in semantic conventions 1.27. `env` is not a
# convention at all — it is where a Datadog `env:` tag lands, because that ingest
# path stores tags verbatim. First non-empty wins.
_ENVIRONMENT_KEYS = ("deployment.environment.name", "deployment.environment", "env")

# A truncated count is worse than no count: it becomes a permanent baseline the
# detector trusts, and nothing downstream can tell it apart from a real drop. So
# reads throw at the budget rather than returning what they managed to scan.
# The cap is generous against a 5-minute window and only trips on runaway volume.
_AGGREGATION_QUERY_SETTINGS = {
    "max_execution_time": int(os.environ.get("LOGS_VOLUME_TICK_AGGREGATION_MAX_EXECUTION_SECONDS", "55")),
    "max_bytes_to_read": int(os.environ.get("LOGS_VOLUME_TICK_AGGREGATION_MAX_BYTES_TO_READ", str(20 * 1024**3))),
    "read_overflow_mode": "throw",
}


@frozen
class AggregationResult:
    rows_written: int


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


def _aggregation_sql() -> str:
    environment = _first_non_empty_map_key("resource_attributes", "env_key_", len(_ENVIRONMENT_KEYS))
    # Dimensions are stored verbatim, with '' for absent. No 'unknown' sentinel:
    # it would change which rows group together, and the correctness test
    # compares these counts against a direct count of the same raw logs.
    #
    # severity_text is the exception. It is lowercased because an issue's identity
    # will include it, so a service emitting ERROR one week and error the next
    # would file two issues for one problem.
    return f"""
        INSERT INTO {TABLE_NAME}
            (team_id, time_bucket, generation, service_name, namespace, environment, severity_text, log_count)
        SELECT
            team_id,
            toStartOfInterval(timestamp, INTERVAL %(bucket_seconds)s SECOND) AS time_bucket,
            %(generation)s AS generation,
            service_name,
            resource_attributes[%(namespace_key)s] AS namespace,
            {environment} AS environment,
            lower(severity_text) AS severity_text,
            count() AS log_count
        FROM {_SOURCE_TABLE}
        WHERE team_id IN %(team_ids)s
            AND timestamp >= %(start)s
            AND timestamp < %(end)s
        GROUP BY team_id, time_bucket, service_name, namespace, environment, severity_text
    """


def aggregate_buckets(
    *,
    team_ids: Sequence[int],
    start: datetime,
    end: datetime,
    generation: int,
) -> AggregationResult:
    """Write one complete generation of rollup rows for every grid bucket in [start, end).

    Writes only. Nothing here makes the rows visible: readers filter to the
    (time_bucket, generation) pairs committed in Postgres, so a partial or
    abandoned attempt is invisible rather than wrong. Callers therefore commit
    strictly after this returns, and never before.

    Raises `CHQueryErrorTooManyBytes` if the scan exceeds its byte budget.
    """
    if not team_ids:
        raise ValueError("aggregate_buckets requires at least one team id")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError(f"start {start.isoformat()} must precede end {end.isoformat()}")
    for name, boundary in (("start", start), ("end", end)):
        if int(boundary.timestamp()) % BUCKET_SECONDS:
            raise ValueError(f"{name} {boundary.isoformat()} is not aligned to the {BUCKET_SECONDS}s grid")

    parameters: dict[str, object] = {
        "team_ids": list(team_ids),
        "start": start,
        "end": end,
        "generation": generation,
        "bucket_seconds": BUCKET_SECONDS,
        "namespace_key": _NAMESPACE_KEY,
    }
    parameters.update({f"env_key_{index}": key for index, key in enumerate(_ENVIRONMENT_KEYS)})

    with tags_context(product=Product.LOGS, feature=Feature.PREAGGREGATION):
        result = sync_execute(
            _aggregation_sql(),
            parameters,
            workload=Workload.LOGS,
            settings=_AGGREGATION_QUERY_SETTINGS,
        )
    # sync_execute swaps an INSERT's result for ClickHouse's written_rows counter,
    # but only when that counter is nonzero, so "not an int" is exactly zero rows.
    return AggregationResult(rows_written=result if isinstance(result, int) else 0)
