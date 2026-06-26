import datetime as dt

import pytest

from products.metrics.backend.facade.contracts import (
    MAX_CLAUSES_PER_QUERY,
    MetricFilter,
    MetricGroupBy,
    MetricPoint,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
)
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation


def _clause(**overrides) -> MetricQueryClause:
    base = {"name": "a", "metric_name": "m", "aggregation": MetricAggregation.SUM}
    return MetricQueryClause(**{**base, **overrides})


class TestMetricQueryClause:
    def test_minimal_clause(self):
        clause = _clause()
        assert clause.filters == ()
        assert clause.group_by == ()
        assert clause.quantile is None

    def test_quantile_aggregation_requires_quantile(self):
        with pytest.raises(ValueError):
            _clause(aggregation=MetricAggregation.QUANTILE)
        with pytest.raises(ValueError):
            _clause(aggregation=MetricAggregation.HISTOGRAM_QUANTILE)

    def test_quantile_must_be_in_open_unit_interval(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError):
                _clause(aggregation=MetricAggregation.QUANTILE, quantile=bad)
        assert _clause(aggregation=MetricAggregation.QUANTILE, quantile=0.95).quantile == 0.95

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            _clause(name="")


class TestMetricQueryRequest:
    def _req(self, **overrides) -> MetricQueryRequest:
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
        base = {
            "clauses": (_clause(),),
            "date_from": now - dt.timedelta(hours=1),
            "date_to": now,
        }
        return MetricQueryRequest(**{**base, **overrides})

    def test_minimal_request(self):
        req = self._req()
        assert req.interval is None
        assert req.formula is None

    def test_requires_at_least_one_clause(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
        with pytest.raises(ValueError):
            MetricQueryRequest(clauses=(), date_from=now - dt.timedelta(hours=1), date_to=now)

    def test_rejects_inverted_range(self):
        now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
        with pytest.raises(ValueError):
            MetricQueryRequest(clauses=(_clause(),), date_from=now, date_to=now - dt.timedelta(hours=1))

    def test_rejects_duplicate_clause_names(self):
        with pytest.raises(ValueError):
            self._req(clauses=(_clause(name="a"), _clause(name="a", metric_name="other")))

    def test_rejects_too_many_clauses(self):
        clauses = tuple(_clause(name=f"c{i}") for i in range(MAX_CLAUSES_PER_QUERY + 1))
        with pytest.raises(ValueError):
            self._req(clauses=clauses)

    def test_allows_distinct_clause_names_for_formula(self):
        req = self._req(
            clauses=(_clause(name="a"), _clause(name="b", metric_name="other")),
            formula="a / b",
        )
        assert req.formula == "a / b"


class TestFiltersAndGroupBy:
    def test_filter_defaults_to_auto_scope(self):
        f = MetricFilter(key="container", op=FilterOp.EQ, value="logs-ingestion")
        assert f.scope == AttributeScope.AUTO

    def test_group_by_explicit_scope(self):
        g = MetricGroupBy(key="service_name", scope=AttributeScope.RESOURCE)
        assert g.scope == AttributeScope.RESOURCE


class TestMetricSeries:
    def test_ungrouped_series_has_empty_labels(self):
        series = MetricSeries(labels={}, points=(MetricPoint(time="2026-01-01T00:00:00", value=1.0),))
        assert series.labels == {}
        assert series.points[0].value == 1.0
