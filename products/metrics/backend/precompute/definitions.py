"""Which clauses a precomputed metric can answer, and the definitions that dashboard tiles create.

A clause is a leaf when its value for a bucket is a sum of per-hour values: the summed increase of a counter
(`increase`, `rate`, and their `count_` forms), or the summed bucket counts of a histogram. Those survive being
aggregated in two steps, per hour by the kept labels, then across hours and down to the clause's group-by.
Every other aggregation reads each series' last value in a bucket, which does not, so it runs raw.
"""

import json
import hashlib
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from products.metrics.backend.facade.contracts import DERIVED_METRIC_PREFIX, MetricQueryClause
from products.metrics.backend.facade.enums import (
    AttributeScope,
    MetricAggregation,
    MetricRangeFunction,
    MetricType,
    PrecomputedMetricKind,
)
from products.metrics.backend.models import MetricPrecomputedMetric

MAX_PRECOMPUTED_METRICS_PER_TEAM = 20
MAX_KEPT_LABELS = 5

_KIND_BY_AGGREGATION = {
    MetricAggregation.INCREASE: PrecomputedMetricKind.INCREASE,
    MetricAggregation.RATE: PrecomputedMetricKind.INCREASE,
    MetricAggregation.COUNT_INCREASE: PrecomputedMetricKind.COUNT_INCREASE,
    MetricAggregation.COUNT_RATE: PrecomputedMetricKind.COUNT_INCREASE,
    MetricAggregation.HISTOGRAM_QUANTILE: PrecomputedMetricKind.HISTOGRAM,
}


@dataclass(frozen=True, slots=True)
class LabelRef:
    key: str
    scope: AttributeScope


@dataclass(frozen=True, slots=True)
class Leaf:
    """What a clause needs stored: a metric, a kind, and the labels it filters or groups by, sorted."""

    metric_name: str
    metric_type: MetricType | None
    kind: PrecomputedMetricKind
    labels: tuple[LabelRef, ...]


def leaf_for_clause(clause: MetricQueryClause) -> Leaf | str:
    """Return the clause's leaf, or the reason it runs raw."""
    if clause.metric_name.startswith(DERIVED_METRIC_PREFIX):
        return "the metric is derived from spans or logs"
    kind = _KIND_BY_AGGREGATION.get(clause.aggregation)
    if clause.aggregation == MetricAggregation.SUM and clause.range_function in (
        MetricRangeFunction.INCREASE,
        MetricRangeFunction.RATE,
    ):
        kind = PrecomputedMetricKind.INCREASE
    elif clause.range_function is not None:
        kind = None
    if kind is None:
        return f"the {clause.aggregation} aggregation reads each series' last value, which hourly sums cannot answer"
    labels = sorted(
        {LabelRef(f.key, f.scope) for f in clause.filters} | {LabelRef(g.key, g.scope) for g in clause.group_by},
        key=lambda label: (label.key, label.scope),
    )
    if len({label.key for label in labels}) != len(labels):
        return "the clause reads one label in two scopes"
    if len(labels) > MAX_KEPT_LABELS:
        return f"the clause filters or groups by more than {MAX_KEPT_LABELS} labels"
    return Leaf(metric_name=clause.metric_name, metric_type=clause.metric_type, kind=kind, labels=tuple(labels))


def labels_of(precomputed_metric: MetricPrecomputedMetric) -> tuple[LabelRef, ...]:
    return tuple(LabelRef(label["key"], AttributeScope(label["scope"])) for label in precomputed_metric.labels)


def find_precomputed_metric(team_id: int, leaf: Leaf) -> MetricPrecomputedMetric | None:
    """The metric keeping the fewest labels among those that keep every label the leaf reads."""
    candidates = [
        candidate
        for candidate in MetricPrecomputedMetric.objects.for_team(team_id).filter(
            metric_name=leaf.metric_name,
            metric_type=leaf.metric_type.value if leaf.metric_type is not None else "",
            kind=leaf.kind.value,
        )
        if set(leaf.labels) <= set(labels_of(candidate))
    ]
    return min(candidates, key=lambda candidate: (len(candidate.labels), candidate.created_at), default=None)


def get_or_create_precomputed_metric(team_id: int, leaf: Leaf) -> MetricPrecomputedMetric | None:
    """Find the leaf's metric or create one keeping exactly its labels. None when the team has no free slot."""
    existing = find_precomputed_metric(team_id, leaf)
    if existing is not None:
        return existing
    used_slots = set(MetricPrecomputedMetric.objects.for_team(team_id).values_list("slot", flat=True))
    slot = next((slot for slot in range(MAX_PRECOMPUTED_METRICS_PER_TEAM) if slot not in used_slots), None)
    if slot is None:
        return None
    labels = [{"key": label.key, "scope": label.scope.value} for label in leaf.labels]
    try:
        with transaction.atomic():
            return MetricPrecomputedMetric.objects.for_team(team_id).create(
                team_id=team_id,
                slot=slot,
                metric_name=leaf.metric_name,
                metric_type=leaf.metric_type.value if leaf.metric_type is not None else "",
                kind=leaf.kind.value,
                labels=labels,
                labels_key=hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest(),
                last_used_at=timezone.now(),
            )
    except IntegrityError:
        # A concurrent tile created the same metric or took the slot. Either way, don't exceed the cap.
        return find_precomputed_metric(team_id, leaf)
