"""Distinct metric names for a team's picker UI.

Reads `metric_series` (one row per metric + label-set) rather than the raw
`metrics` datapoint table. Both are fed from the same Kafka Avro stream, so
they carry the same names, but the series table holds one row per series
where the datapoint table holds one per scrape, so it is orders of magnitude
smaller for the same window. It also sorts by `(team_id, metric_name,
series_fingerprint)` with a materialized `last_seen`, so the lookback needs no
scan over the datapoint rows.

No FINAL. ReplacingMergeTree duplicates share `(team_id, metric_name,
series_fingerprint)`, and `max(last_seen)` picks the row FINAL would keep, since
`last_seen` is the engine's version column. `metric_type` is an input to the
fingerprint (see `rust/capture-logs/src/metric_record.rs`), so every duplicate
of one fingerprint agrees on it and `any()` cannot return a stale type.

Surfaces `metric_type` alongside the name so the viewer can hint at the
type-appropriate default aggregation (gauge -> avg, counter/sum -> sum, etc.)
without a second round-trip.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.search import AUTOCOMPLETE_QUERY_SETTINGS, ilike_pattern

# Both `metric_series` and `metrics` expire at the same `original_expiry_timestamp`,
# which ingest sets to the team's retention (90 days by default).
# A lookback beyond this would quietly return fewer names than the raw table has.
SERIES_RETENTION = dt.timedelta(days=90)

# Past this the picker is not scoped to anything a person can hold in their head,
# and the bound keeps one request from building an unbounded IN list.
MAX_PICKER_SERVICES = 50


def _isoformat(value: Any) -> str | None:
    """ClickHouse hands back datetimes, but a driver or JSON round-trip can leave a
    string. The API serializer accepts ISO either way, so normalize without assuming."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class MetricNamesQueryRunner:
    def __init__(
        self,
        team: Team,
        *,
        search: str = "",
        limit: int = 100,
        lookback: dt.timedelta = dt.timedelta(days=7),
        services: Sequence[str] = (),
    ) -> None:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")
        if len(services) > MAX_PICKER_SERVICES:
            raise ValueError(f"at most {MAX_PICKER_SERVICES} services may be selected")

        self.team = team
        self.search = search.strip()
        self.limit = limit
        self.lookback = lookback
        # Sorted and deduped so two callers that picked the same services in a
        # different order share one cache entry. An empty string is a real
        # selection: a sender that omits the `service.name` resource attribute
        # lands in the group the overview labels "unknown".
        self.services = tuple(sorted(set(services)))

    def _build_query(self) -> ast.SelectQuery:
        # The alias is `last_seen_at`, not `last_seen`: HogQL registers select
        # aliases before it resolves WHERE and prefers an alias over a table
        # column, so `max(last_seen) AS last_seen` would put an aggregate in the
        # WHERE clause.
        lookback = ast.Call(name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))])

        if not self.search:
            # With no search the ILIKE ('%%') and the exact-match sort key are
            # both no-ops. They're dropped rather than passed as neutral
            # constants: ClickHouse reads a bare integer in ORDER BY positionally.
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        max(last_seen) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen > now() - {lookback}
                    GROUP BY metric_name
                    ORDER BY last_seen_at DESC
                    LIMIT {limit}
                """,
                placeholders={"lookback": lookback, "limit": ast.Constant(value=self.limit)},
            )
        else:
            query = parse_select(
                """
                    SELECT
                        metric_name AS name,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        max(last_seen) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen > now() - {lookback}
                      AND metric_name ILIKE {search_pattern}
                    GROUP BY metric_name
                    ORDER BY
                        lower(metric_name) = lower({exact}) DESC,
                        last_seen_at DESC
                    LIMIT {limit}
                """,
                placeholders={
                    "lookback": lookback,
                    "search_pattern": ast.Constant(value=ilike_pattern(self.search)),
                    "exact": ast.Constant(value=self.search),
                    "limit": ast.Constant(value=self.limit),
                },
            )

        assert isinstance(query, ast.SelectQuery)
        # Both variants above filter on the lookback, so there is always a WHERE to
        # extend; the assert is what tells the type checker so.
        assert query.where is not None

        # Appended to the parsed tree rather than written into both SQL variants
        # above, so the scoped and unscoped pickers stay one query definition.
        # `service_name` is the only filterable column with its own skip index
        # (`idx_service_set`), which is what keeps a type-ahead affordable —
        # attribute predicates read the label maps and belong in the chart query.
        if self.services:
            query.where = ast.And(
                exprs=[
                    query.where,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=ast.Field(chain=["service_name"]),
                        right=ast.Tuple(exprs=[ast.Constant(value=service) for service in self.services]),
                    ),
                ]
            )
        return query

    def run(self) -> list[dict[str, Any]]:
        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=self._build_query(),
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=AUTOCOMPLETE_QUERY_SETTINGS,
        )

        return [
            {
                "name": row[0],
                "metric_type": row[1],
                "unit": row[2],
                "last_seen": _isoformat(row[3]),
            }
            for row in response.results
        ]


def metric_names(
    team: Team, *, search: str = "", limit: int = 100, services: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Metric names for the picker."""
    return MetricNamesQueryRunner(team=team, search=search, limit=limit, services=services).run()
