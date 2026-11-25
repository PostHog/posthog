import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from parameterized import parameterized

from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy, MetricQueryClause, MetricQueryRequest
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation
from products.metrics.backend.models import MetricPrecomputedMetric
from products.metrics.backend.precompute.planner import ClausePlan, PrecomputedClauseRunner
from products.metrics.backend.precompute.store import Entry

LONDON = ZoneInfo("Europe/London")
# 2026-10-25 01:00 local happens twice in London: 00:00 UTC (BST) and 01:00 UTC (GMT).
FALLBACK_FROM = dt.datetime(2026, 10, 24, 23, tzinfo=dt.UTC)


def _runner(filters: tuple[MetricFilter, ...] = ()) -> PrecomputedClauseRunner:
    clause = MetricQueryClause(
        name="a",
        metric_name="requests_total",
        aggregation=MetricAggregation.SUM,
        filters=filters,
        group_by=(MetricGroupBy(key="service_name"),),
    )
    metric = MetricPrecomputedMetric(labels=[{"key": "service_name", "scope": "auto"}])
    date_to = FALLBACK_FROM + dt.timedelta(hours=4)
    plan = ClausePlan(clause=clause, precomputed_metric=metric, interval="hour", date_from=FALLBACK_FROM, cut=date_to)
    request = MetricQueryRequest(clauses=(clause,), date_from=FALLBACK_FROM, date_to=date_to, interval="hour")
    return PrecomputedClauseRunner(SimpleNamespace(timezone_info=LONDON), request, plan, {})  # type: ignore[arg-type]


def _entry(service: str) -> Entry:
    hours = [FALLBACK_FROM + dt.timedelta(hours=offset) for offset in range(4)]
    return Entry(labels=(service,), fingerprints={1}, points=dict.fromkeys(hours, 1.0))


class TestPrecomputedCounterRows:
    def test_repeated_hour_of_a_dst_fallback_stays_two_buckets(self) -> None:
        rows = _runner()._counter_rows([_entry("api")])

        assert [(row["time"], row["value"]) for row in rows] == [
            ("2026-10-25T00:00:00+01:00", 1.0),
            ("2026-10-25T01:00:00+01:00", 1.0),
            ("2026-10-25T01:00:00+00:00", 1.0),
            ("2026-10-25T02:00:00+00:00", 1.0),
        ]

    @parameterized.expand(
        [
            ("dot_matches_newline", FilterOp.REGEX, "^api.*$", True),
            ("negated_dot_matches_newline", FilterOp.NOT_REGEX, "^api.*$", False),
        ]
    )
    def test_regex_filter_matches_like_clickhouse(self, _name: str, op: FilterOp, pattern: str, kept: bool) -> None:
        runner = _runner(filters=(MetricFilter(key="service_name", op=op, value=pattern),))

        assert bool(runner._counter_rows([_entry("api\nworker")])) is kept
