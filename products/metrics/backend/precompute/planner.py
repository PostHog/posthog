"""The planner: answers a clause's past buckets from a precomputed metric and only the newest ones from raw samples.

A clause is planned when it is a leaf (`definitions.leaf_for_clause`), its interval is whole hours on a project
timezone with a whole-hour offset, and a precomputed metric covers its range back to the first bucket. The cut is
the last bucket boundary at or before the end of the stored hours. Buckets before the cut sum the stored hours,
and buckets from the cut on run through the ordinary runner. Since the cut is a bucket boundary, no bucket
mixes the two. Anything else runs exactly as without the planner.
"""

import re
import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter, MetricQueryClause, MetricQueryRequest
from products.metrics.backend.facade.enums import (
    FilterOp,
    MetricAggregation,
    MetricQueryProvenanceMode,
    MetricRangeFunction,
    PrecomputedMetricKind,
)
from products.metrics.backend.metric_query_runner import (
    MetricQueryRunner,
    _align_to_interval,
    _finite_or_none,
    _interval_step,
    _resolve_interval,
)
from products.metrics.backend.metric_samples_query_runner import build_metric_query_runner
from products.metrics.backend.models import MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import (
    find_precomputed_metric,
    get_or_create_precomputed_metric,
    labels_of,
    leaf_for_clause,
)
from products.metrics.backend.precompute.fill import whole_hour_offset
from products.metrics.backend.precompute.store import HOUR, Entry, read_entries

# A tile over a shorter range reads little raw data, so it doesn't create a precomputed metric.
MIN_RANGE_TO_CREATE = dt.timedelta(days=1)
# Past this, the raw tail would cost about as much as the raw query.
MAX_RAW_TAIL = dt.timedelta(days=1)
_LAST_USED_RESOLUTION = dt.timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ClausePlan:
    """A clause answered from storage before `cut` and raw from `cut` to the request's end."""

    clause: MetricQueryClause
    precomputed_metric: MetricPrecomputedMetric
    interval: str
    date_from: dt.datetime
    cut: dt.datetime


def _matches(filter: MetricFilter, value: str) -> bool:
    if filter.op == FilterOp.EQ:
        return value == filter.value
    if filter.op == FilterOp.NEQ:
        return value != filter.value
    # ClickHouse `match` finds the pattern anywhere in the value, as `re.search` does.
    found = re.search(filter.value, value) is not None
    return found if filter.op == FilterOp.REGEX else not found


def _is_rate(clause: MetricQueryClause) -> bool:
    return clause.aggregation in (MetricAggregation.RATE, MetricAggregation.COUNT_RATE) or (
        clause.range_function == MetricRangeFunction.RATE
    )


def plan_clause(team: Team, clause: MetricQueryClause, request: MetricQueryRequest) -> ClausePlan | str:
    """Plan one clause, or return why it runs raw. The first long-range tile that needs a metric creates it."""
    leaf = leaf_for_clause(clause)
    if isinstance(leaf, str):
        return leaf
    interval = _resolve_interval(request.date_from, request.date_to, request.interval)
    if _interval_step(interval) % HOUR or _interval_step(interval) < HOUR:
        return "the interval is shorter than an hour"
    if not whole_hour_offset(team, request.date_from, request.date_to):
        return "the project timezone is not a whole number of hours from UTC"
    precomputed_metric = find_precomputed_metric(team.pk, leaf)
    if precomputed_metric is None:
        if request.date_to - request.date_from < MIN_RANGE_TO_CREATE:
            return "the range is too short to precompute"
        if get_or_create_precomputed_metric(team.pk, leaf) is None:
            return "the project has no room for another precomputed metric"
        return "precomputing started"
    if precomputed_metric.state != MetricPrecomputedMetric.State.ACTIVE:
        return "the precomputed metric is paused"
    _touch(precomputed_metric)
    date_from = _align_to_interval(request.date_from, interval, tzinfo=team.timezone_info)
    covered_from, covered_to = precomputed_metric.covered_from, precomputed_metric.covered_to
    if covered_from is None or covered_to is None or covered_from > date_from:
        return "the precomputed metric is still filling"
    if request.date_to - covered_to > MAX_RAW_TAIL:
        return "the precomputed metric is behind"
    cut = _align_to_interval(min(covered_to, request.date_to), interval, tzinfo=team.timezone_info)
    if cut <= date_from:
        return "less than one bucket is stored"
    return ClausePlan(
        clause=clause, precomputed_metric=precomputed_metric, interval=interval, date_from=date_from, cut=cut
    )


def _touch(precomputed_metric: MetricPrecomputedMetric) -> None:
    now = timezone.now()
    if precomputed_metric.last_used_at < now - _LAST_USED_RESOLUTION:
        MetricPrecomputedMetric.objects.for_team(precomputed_metric.team_id).filter(pk=precomputed_metric.pk).update(
            last_used_at=now
        )


class PrecomputedClauseRunner:
    """Rows shaped like `MetricQueryRunner.run`: stored buckets before the cut, the ordinary runner after it."""

    def __init__(self, team: Team, request: MetricQueryRequest, plan: ClausePlan) -> None:
        self.team = team
        self.request = request
        self.plan = plan
        # Read here, on the caller's thread: `run` runs on a worker thread, which shouldn't take a Postgres connection.
        self.entries = read_entries(plan.precomputed_metric, plan.date_from, plan.cut)

    def _runner(self, date_from: dt.datetime, date_to: dt.datetime) -> MetricQueryRunner:
        clause = self.plan.clause
        aggregation = clause.aggregation.value
        return build_metric_query_runner(
            team=self.team,
            metric_name=clause.metric_name,
            aggregation=aggregation,
            date_from=date_from,
            date_to=date_to,
            filters=clause.filters,
            group_by=clause.group_by,
            interval=self.plan.interval,
            quantile=clause.quantile if aggregation == "histogram_quantile" else None,
            metric_type=clause.metric_type.value if clause.metric_type is not None else None,
            range_function=clause.range_function.value if clause.range_function is not None else None,
        )

    def run(self) -> list[dict[str, Any]]:
        plan = self.plan
        entries = self.entries
        if plan.precomputed_metric.kind == PrecomputedMetricKind.HISTOGRAM:
            rows = self._runner(self.request.date_from, self.request.date_to).quantile_rows(
                self._histogram_results(entries.values())
            )
        else:
            rows = self._counter_rows(entries.values())
        if plan.cut < self.request.date_to:
            rows.extend(self._runner(plan.cut, self.request.date_to).run())
        return rows

    def _kept(self, entry: Entry) -> tuple[str, ...] | None:
        """The entry's values of the clause's group-by labels, or None when the clause's filters drop it."""
        values = {label.key: value for label, value in zip(labels_of(self.plan.precomputed_metric), entry.labels)}
        if not all(_matches(f, values[f.key]) for f in self.plan.clause.filters):
            return None
        return tuple(values[group.key] for group in self.plan.clause.group_by)

    def _bucket(self, hour: dt.datetime) -> dt.datetime:
        tzinfo = self.team.timezone_info
        return _align_to_interval(hour, self.plan.interval, tzinfo=tzinfo).astimezone(tzinfo)

    def _counter_rows(self, entries: Sequence[Entry] | Any) -> list[dict[str, Any]]:
        divisor = _interval_step(self.plan.interval).total_seconds() if _is_rate(self.plan.clause) else 1.0
        sums: dict[tuple[dt.datetime, tuple[str, ...]], float] = {}
        fingerprints: dict[tuple[dt.datetime, tuple[str, ...]], set[int]] = {}
        for entry in entries:
            group = self._kept(entry)
            if group is None:
                continue
            for hour, value in entry.points.items():
                key = (self._bucket(hour), group)
                sums[key] = sums.get(key, 0.0) + float(value)  # type: ignore[arg-type]
                fingerprints.setdefault(key, set()).update(entry.fingerprints)
        group_keys = [group.key for group in self.plan.clause.group_by]
        return [
            {
                "time": time.isoformat(),
                "value": _finite_or_none(total / divisor),
                "labels": dict(zip(group_keys, group)),
                "series_fingerprints": sorted(fingerprints[(time, group)]),
            }
            for (time, group), total in sorted(sums.items())
        ]

    def _histogram_results(self, entries: Sequence[Entry] | Any) -> list[Any]:
        """Rows shaped like `MetricQueryRunner.histogram_rows`, summed from the stored hours."""
        counts: dict[tuple[dt.datetime, tuple[str, ...], tuple[float, ...], str], list[float]] = {}
        fingerprints: dict[tuple[dt.datetime, tuple[str, ...], tuple[float, ...], str], set[int]] = {}
        for entry in entries:
            group = self._kept(entry)
            if group is None:
                continue
            for hour, value in entry.points.items():
                key = (self._bucket(hour), group, entry.bounds, entry.metric_type)
                summed = counts.setdefault(key, [0.0] * len(value))  # type: ignore[arg-type]
                for index, count in enumerate(value):  # type: ignore[arg-type]
                    summed[index] += count
                fingerprints.setdefault(key, set()).update(entry.fingerprints)
        return [
            (time, *group, list(bounds), summed, sorted(fingerprints[key]), metric_type)
            for key, summed in sorted(counts.items())
            for time, group, bounds, metric_type in [key]
        ]


def provenance_mode(planned: Sequence[ClausePlan], raw_count: int, date_to: dt.datetime) -> MetricQueryProvenanceMode:
    if not planned:
        return MetricQueryProvenanceMode.RAW
    if raw_count == 0 and all(plan.cut >= date_to for plan in planned):
        return MetricQueryProvenanceMode.PRECOMPUTED
    return MetricQueryProvenanceMode.MIXED
