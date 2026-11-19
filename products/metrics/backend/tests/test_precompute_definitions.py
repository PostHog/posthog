import dataclasses
from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy, MetricQueryClause
from products.metrics.backend.facade.enums import (
    AttributeScope,
    FilterOp,
    MetricAggregation,
    MetricRangeFunction,
    MetricType,
    PrecomputedMetricKind,
)
from products.metrics.backend.models import MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import (
    MAX_PRECOMPUTED_METRICS_PER_TEAM,
    LabelRef,
    Leaf,
    find_precomputed_metric,
    get_or_create_precomputed_metric,
    leaf_for_clause,
)


def _clause(aggregation: MetricAggregation, **overrides: Any) -> MetricQueryClause:
    clause = MetricQueryClause(
        name="a",
        metric_name="requests_total",
        aggregation=aggregation,
        quantile=0.95 if aggregation.needs_quantile else None,
    )
    return dataclasses.replace(clause, **overrides)


class TestLeafForClause(SimpleTestCase):
    @parameterized.expand(
        [
            ("increase", _clause(MetricAggregation.INCREASE), PrecomputedMetricKind.INCREASE),
            ("rate", _clause(MetricAggregation.RATE), PrecomputedMetricKind.INCREASE),
            (
                "sum_of_increase",
                _clause(MetricAggregation.SUM, range_function=MetricRangeFunction.INCREASE),
                PrecomputedMetricKind.INCREASE,
            ),
            (
                "sum_of_rate",
                _clause(MetricAggregation.SUM, range_function=MetricRangeFunction.RATE),
                PrecomputedMetricKind.INCREASE,
            ),
            ("count_increase", _clause(MetricAggregation.COUNT_INCREASE), PrecomputedMetricKind.COUNT_INCREASE),
            ("count_rate", _clause(MetricAggregation.COUNT_RATE), PrecomputedMetricKind.COUNT_INCREASE),
            (
                "histogram_quantile",
                _clause(MetricAggregation.HISTOGRAM_QUANTILE),
                PrecomputedMetricKind.HISTOGRAM,
            ),
        ]
    )
    def test_supported_shapes_are_leaves(self, _name: str, clause: MetricQueryClause, kind: PrecomputedMetricKind):
        leaf = leaf_for_clause(clause)
        assert isinstance(leaf, Leaf)
        assert leaf.kind == kind

    @parameterized.expand(
        [
            ("gauge_sum", _clause(MetricAggregation.SUM)),
            ("gauge_max", _clause(MetricAggregation.MAX)),
            ("avg", _clause(MetricAggregation.AVG)),
            ("series_count", _clause(MetricAggregation.COUNT)),
            ("quantile_over_series", _clause(MetricAggregation.QUANTILE)),
            ("raw_series", _clause(MetricAggregation.NONE)),
            ("max_of_rate", _clause(MetricAggregation.MAX, range_function=MetricRangeFunction.RATE)),
            ("derived_from_spans", _clause(MetricAggregation.INCREASE, metric_name="posthog.derived.span_count")),
            (
                "same_key_in_two_scopes",
                _clause(
                    MetricAggregation.INCREASE,
                    filters=(MetricFilter(key="env", op=FilterOp.EQ, value="prod", scope=AttributeScope.RESOURCE),),
                    group_by=(MetricGroupBy(key="env", scope=AttributeScope.ATTRIBUTE),),
                ),
            ),
            (
                "too_many_labels",
                _clause(MetricAggregation.INCREASE, group_by=tuple(MetricGroupBy(key=f"k{i}") for i in range(6))),
            ),
        ]
    )
    def test_other_shapes_run_raw_with_a_reason(self, _name: str, clause: MetricQueryClause):
        reason = leaf_for_clause(clause)
        assert isinstance(reason, str) and reason

    def test_keeps_every_label_the_clause_filters_or_groups_by(self):
        leaf = leaf_for_clause(
            _clause(
                MetricAggregation.RATE,
                metric_type=MetricType.SUM,
                filters=(MetricFilter(key="status", op=FilterOp.REGEX, value="5.."),),
                group_by=(MetricGroupBy(key="service_name"), MetricGroupBy(key="status")),
            )
        )
        assert leaf == Leaf(
            metric_name="requests_total",
            metric_type=MetricType.SUM,
            kind=PrecomputedMetricKind.INCREASE,
            labels=(LabelRef("service_name", AttributeScope.AUTO), LabelRef("status", AttributeScope.AUTO)),
        )


class TestGetOrCreatePrecomputedMetric(BaseTest):
    def _leaf(self, *keys: str, metric_name: str = "requests_total") -> Leaf:
        return Leaf(
            metric_name=metric_name,
            metric_type=None,
            kind=PrecomputedMetricKind.INCREASE,
            labels=tuple(LabelRef(key, AttributeScope.AUTO) for key in sorted(keys)),
        )

    def test_creates_once_and_reuses_it(self):
        first = get_or_create_precomputed_metric(self.team.pk, self._leaf("service_name"))
        second = get_or_create_precomputed_metric(self.team.pk, self._leaf("service_name"))
        assert first is not None and second is not None
        assert first.pk == second.pk
        assert MetricPrecomputedMetric.objects.for_team(self.team.pk).count() == 1

    def test_a_metric_keeping_more_labels_serves_a_clause_needing_fewer(self):
        wide = get_or_create_precomputed_metric(self.team.pk, self._leaf("service_name", "status"))
        assert wide is not None
        found = find_precomputed_metric(self.team.pk, self._leaf("status"))
        assert found is not None and found.pk == wide.pk
        assert find_precomputed_metric(self.team.pk, self._leaf("route")) is None

    def test_stops_creating_at_the_team_cap(self):
        for index in range(MAX_PRECOMPUTED_METRICS_PER_TEAM):
            assert get_or_create_precomputed_metric(self.team.pk, self._leaf(metric_name=f"m{index}")) is not None
        assert get_or_create_precomputed_metric(self.team.pk, self._leaf(metric_name="one_too_many")) is None
        assert MetricPrecomputedMetric.objects.for_team(self.team.pk).count() == MAX_PRECOMPUTED_METRICS_PER_TEAM

    def test_the_cap_is_per_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        for index in range(MAX_PRECOMPUTED_METRICS_PER_TEAM):
            get_or_create_precomputed_metric(self.team.pk, self._leaf(metric_name=f"m{index}"))
        assert get_or_create_precomputed_metric(other_team.pk, self._leaf()) is not None

    def test_keeps_the_bucket_width_of_the_leaf_apart(self):
        six_hours = Leaf(
            metric_name="latency_seconds_bucket",
            metric_type=None,
            kind=PrecomputedMetricKind.BUCKET_INCREASE,
            labels=(LabelRef("le", AttributeScope.AUTO),),
            bucket_seconds=6 * 3600,
        )
        created = get_or_create_precomputed_metric(self.team.pk, six_hours)
        assert created is not None and created.bucket_seconds == 6 * 3600
        one_hour = dataclasses.replace(six_hours, bucket_seconds=3600)
        assert find_precomputed_metric(self.team.pk, one_hour) is None
        hourly = get_or_create_precomputed_metric(self.team.pk, one_hour)
        assert hourly is not None and hourly.pk != created.pk and hourly.bucket_seconds == 3600
