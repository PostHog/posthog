"""PromQL tiles answered from precomputed metrics.

Two shapes are planned, and every other query runs raw, exactly as without the planner:

- `sum by (G) (sum_over_time(m{M}[w]))` on any metric type, optionally wrapped in `topk`, `bottomk`, `sort` or
  `sort_desc`. It reads `sum_over_time(m[R])` stored per bucket `R` and by the labels in `G` and `M`, so a step's
  window `(t - w, t]` is the sum of the buckets inside it. That is exact.
- `histogram_quantile(q, sum by (le) (increase(m_bucket{M}[w])))`. It reads `increase(m_bucket[R])` stored per
  bucket by `le` and `M`'s labels. Snuffle's `increase` over a delta histogram is the sum of its points in the
  window, so summed buckets are exact for any `w`. Delta histograms use 6-hour buckets, the windows their tiles
  read (see DERIVED_METRICS.md). Over a cumulative histogram, a window wider than one bucket sums per-bucket
  increases, which skip the step between buckets that Prometheus' extrapolation adds back, so it can read low.

Fills and the raw tail both go through Snuffle with the same bucket query, so stored buckets are what a raw query
would read. The buckets after the stored ones are read raw, and every step sums its window from both, so a 7-day
window reads at most the newest few hours raw. `w`, the step and the first step must all fall on bucket boundaries.
"""

import re
import math
import datetime as dt
from collections.abc import Iterator, Sequence
from functools import lru_cache
from typing import Any

from django.utils import timezone

import re2

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.dashboard_import.promql_text import Token, tokenize
from products.metrics.backend.facade.enums import AttributeScope, PrecomputedMetricKind
from products.metrics.backend.metric_query_runner import (
    _QUERY_SETTINGS,
    _align_to_interval,
    _interval_step,
    _resolve_interval,
)
from products.metrics.backend.models import MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import (
    MAX_KEPT_LABELS,
    NOT_STARTED_BY_VIEWER,
    LabelRef,
    Leaf,
    find_precomputed_metric,
    get_or_create_precomputed_metric,
    labels_of,
)
from products.metrics.backend.precompute.fill import query_promql_buckets
from products.metrics.backend.precompute.store import (
    Entry,
    EntryKey,
    TooManyStoredPointsError,
    bucket_width,
    read_entries,
)
from products.metrics.backend.promql import fill_range_variables

HOUR = dt.timedelta(hours=1)
DELTA_HISTOGRAM_BUCKET = dt.timedelta(hours=6)
# A tile over a shorter range reads little raw data, so it doesn't create a precomputed metric.
MIN_RANGE_TO_CREATE = dt.timedelta(days=1)
# Past this, the raw tail would cost about as much as the raw query.
MAX_RAW_TAIL = dt.timedelta(days=1)
# Stored label-set buckets that one request may load. Past this, the tile runs raw.
MAX_STORED_POINTS = 500_000
_LAST_USED_RESOLUTION = dt.timedelta(hours=1)
_STEP_WINDOWS = frozenset({"$__interval", "${__interval}", "$__rate_interval", "${__rate_interval}"})
_DURATION = re.compile(r"(\d+)(ms|s|m|h|d|w|y)")
_DURATION_TEXT = re.compile(r"(?:\d+(?:ms|s|m|h|d|w|y))+")
# Longer windows can't be stored anyway, and a bounded token keeps parsing cheap and the date arithmetic in range.
_MAX_DURATION_TEXT_LENGTH = 32
_MAX_WINDOW = dt.timedelta(days=400)
MAX_EXPANDED_POINTS = 2_000_000
_MILLISECOND = dt.timedelta(milliseconds=1)
_DURATION_UNITS = {
    "ms": dt.timedelta(milliseconds=1),
    "s": dt.timedelta(seconds=1),
    "m": dt.timedelta(minutes=1),
    "h": HOUR,
    "d": dt.timedelta(days=1),
    "w": dt.timedelta(weeks=1),
    "y": dt.timedelta(days=365),
}
_ESCAPES = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t", "r": "\r"}
_SORTS = frozenset({"sort", "sort_desc"})
_RANKS = frozenset({"topk", "bottomk"})


@lru_cache(maxsize=256)
def _anchored(pattern: str) -> re2._Regexp:
    # Prometheus anchors a matcher's regex at both ends.
    return re2.compile(f"^(?:{pattern})$")


@frozen
class Matcher:
    label: str
    op: str
    value: str

    def matches(self, value: str) -> bool:
        if self.op == "=":
            return value == self.value
        if self.op == "!=":
            return value != self.value
        found = _anchored(self.value).search(value) is not None
        return found if self.op == "=~" else not found


@frozen
class PromQLLeafQuery:
    """A parsed planned shape. `window` is None when the query reads one step, as `[$__interval]` does."""

    kind: PrecomputedMetricKind
    metric_name: str
    matchers: tuple[Matcher, ...]
    group_by: tuple[str, ...]
    window: dt.timedelta | None
    quantile: float | None = None
    rank: str | None = None
    k: int | None = None

    @property
    def kept_labels(self) -> tuple[str, ...]:
        return tuple(sorted({m.label for m in self.matchers} | set(self.group_by)))


class _Unsupported(Exception):
    pass


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens: list[Token] = [token for token in tokenize(text) if token.kind != "space"]
        self.index = 0

    def peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self, text: str | None = None, kind: str | None = None) -> Token:
        token = self.peek()
        if token is None or (text is not None and token.text != text) or (kind is not None and token.kind != kind):
            raise _Unsupported
        self.index += 1
        return token

    def at(self, text: str) -> bool:
        token = self.peek()
        return token is not None and token.text == text

    def done(self) -> bool:
        return self.index == len(self.tokens)


def _string(token: Token) -> str:
    text = token.text
    if text[0] == "`":
        return text[1:-1]
    body, out, index = text[1:-1], [], 0
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 1
            if index >= len(body) or body[index] not in _ESCAPES:
                raise _Unsupported
            out.append(_ESCAPES[body[index]])
        else:
            out.append(char)
        index += 1
    return "".join(out)


def parse_duration(text: str) -> dt.timedelta | None:
    if not text or len(text) > _MAX_DURATION_TEXT_LENGTH or not _DURATION_TEXT.fullmatch(text):
        return None
    # Sum in whole milliseconds first: a timedelta overflows on amounts far past any window we'd accept.
    milliseconds = sum(
        int(amount) * (_DURATION_UNITS[unit] // _MILLISECOND) for amount, unit in _DURATION.findall(text)
    )
    return dt.timedelta(milliseconds=milliseconds) if milliseconds <= _MAX_WINDOW // _MILLISECOND else None


def _labels(parser: _Parser) -> tuple[str, ...]:
    parser.take("(")
    labels: list[str] = []
    while not parser.at(")"):
        labels.append(parser.take(kind="ident").text)
        if not parser.at(")"):
            parser.take(",")
    parser.take(")")
    return tuple(labels)


@frozen
class _Selector:
    metric_name: str
    matchers: tuple[Matcher, ...]
    window: dt.timedelta | None
    group_by: tuple[str, ...] = ()


def _selector(parser: _Parser) -> _Selector:
    metric_name = parser.take(kind="ident").text
    matchers: list[Matcher] = []
    if parser.at("{"):
        parser.take("{")
        while not parser.at("}"):
            label = parser.take(kind="ident").text
            op = parser.take().text
            if op not in ("=", "!=", "=~", "!~") or label == "__name__":
                raise _Unsupported
            value = _string(parser.take(kind="string"))
            if op in ("=~", "!~"):
                try:
                    _anchored(value)
                except re2.error:
                    raise _Unsupported
            matchers.append(Matcher(label=label, op=op, value=value))
            if not parser.at("}"):
                parser.take(",")
        parser.take("}")
    window: dt.timedelta | None = None
    if parser.at("["):
        parser.take("[")
        token = parser.take()
        if token.text not in _STEP_WINDOWS:
            window = parse_duration(token.text)
            if window is None or window <= dt.timedelta():
                raise _Unsupported
        parser.take("]")
    return _Selector(metric_name=metric_name, matchers=tuple(matchers), window=window)


def _sum(parser: _Parser, function: str) -> _Selector:
    """`sum [by (G)] (function(selector)) [by (G)]`, as the selector and the group-by."""
    parser.take("sum")
    group_by: tuple[str, ...] = ()
    if parser.at("by"):
        parser.take("by")
        group_by = _labels(parser)
    parser.take("(")
    parser.take(function)
    parser.take("(")
    selector = _selector(parser)
    parser.take(")")
    parser.take(")")
    if parser.at("by") and not group_by:
        parser.take("by")
        group_by = _labels(parser)
    return _Selector(
        metric_name=selector.metric_name, matchers=selector.matchers, window=selector.window, group_by=group_by
    )


def _sum_over_time(parser: _Parser) -> PromQLLeafQuery:
    token = parser.peek()
    if token is not None and token.text in _SORTS:
        parser.take()
        parser.take("(")
        inner = _sum_over_time(parser)
        parser.take(")")
        return inner
    if token is not None and token.text in _RANKS:
        parser.take()
        parser.take("(")
        k = parser.take(kind="number").text
        if not k.isdigit() or int(k) < 1:
            raise _Unsupported
        parser.take(",")
        inner = _sum_over_time(parser)
        parser.take(")")
        if inner.rank is not None:
            raise _Unsupported
        return PromQLLeafQuery(
            kind=inner.kind,
            metric_name=inner.metric_name,
            matchers=inner.matchers,
            group_by=inner.group_by,
            window=inner.window,
            rank=token.text,
            k=int(k),
        )
    summed = _sum(parser, "sum_over_time")
    return PromQLLeafQuery(
        kind=PrecomputedMetricKind.SUM_OVER_TIME,
        metric_name=summed.metric_name,
        matchers=summed.matchers,
        group_by=summed.group_by,
        window=summed.window,
    )


def _histogram_quantile(parser: _Parser) -> PromQLLeafQuery:
    parser.take("histogram_quantile")
    parser.take("(")
    try:
        quantile = float(parser.take(kind="number").text)
    except ValueError:
        raise _Unsupported
    parser.take(",")
    summed = _sum(parser, "increase")
    parser.take(")")
    if (
        not summed.metric_name.endswith("_bucket")
        or "le" not in summed.group_by
        or any(m.label == "le" for m in summed.matchers)
    ):
        raise _Unsupported
    return PromQLLeafQuery(
        kind=PrecomputedMetricKind.BUCKET_INCREASE,
        metric_name=summed.metric_name,
        matchers=summed.matchers,
        group_by=summed.group_by,
        window=summed.window,
        quantile=quantile,
    )


def parse_promql(text: str) -> PromQLLeafQuery | str:
    """The planned shape of a query, or why it runs raw."""
    parser = _Parser(text)
    try:
        token = parser.peek()
        if token is not None and token.text == "histogram_quantile":
            query = _histogram_quantile(parser)
        else:
            query = _sum_over_time(parser)
        if not parser.done():
            raise _Unsupported
    except _Unsupported:
        return "the PromQL query is not a shape that precomputed metrics answer"
    if len([label for label in query.kept_labels if label != "le"]) > MAX_KEPT_LABELS:
        return f"the query filters or groups by more than {MAX_KEPT_LABELS} labels"
    return query


def leaf_for_promql(query: PromQLLeafQuery, bucket: dt.timedelta) -> Leaf:
    return Leaf(
        metric_name=query.metric_name,
        metric_type=None,
        kind=query.kind,
        labels=tuple(LabelRef(label, AttributeScope.AUTO) for label in query.kept_labels),
        bucket_seconds=int(bucket.total_seconds()),
    )


def _is_delta_histogram(team: Team, bucket_metric_name: str) -> bool:
    response = execute_hogql_query(
        query_type="MetricsPrecomputeTemporality",
        query=parse_select(
            """
            SELECT aggregation_temporality FROM posthog.metrics
            WHERE metric_name = {name} AND metric_type = 'histogram' AND timestamp >= now() - INTERVAL 2 DAY
            LIMIT 1
            """,
            placeholders={"name": ast.Constant(value=bucket_metric_name.removesuffix("_bucket"))},
        ),
        team=team,
        workload=Workload.METRICS,
        settings=_QUERY_SETTINGS,
    )
    return bool(response.results) and response.results[0][0] == "delta"


def bucket_for(team: Team, query: PromQLLeafQuery) -> dt.timedelta:
    if query.kind == PrecomputedMetricKind.BUCKET_INCREASE and _is_delta_histogram(team, query.metric_name):
        return DELTA_HISTOGRAM_BUCKET
    return HOUR


@frozen
class PromQLPlan:
    """A PromQL tile whose buckets before `cut` are stored, and whose buckets from `cut` to `last_step` read raw."""

    query: PromQLLeafQuery
    precomputed_metric: MetricPrecomputedMetric
    expr: str
    first_step: dt.datetime
    step: dt.timedelta
    window: dt.timedelta
    cut: dt.datetime
    last_step: dt.datetime


def _on_boundary(value: dt.datetime | dt.timedelta, bucket: dt.timedelta) -> bool:
    seconds = value.total_seconds() if isinstance(value, dt.timedelta) else value.timestamp()
    return seconds % bucket.total_seconds() == 0


def plan_promql(
    team: Team,
    text: str,
    date_from: dt.datetime,
    date_to: dt.datetime,
    interval: str | None,
    *,
    record_use: bool = True,
) -> PromQLPlan | str:
    """Plan a PromQL tile, or return why it runs raw. The first long-range tile that needs a metric creates it.

    Without `record_use`, as for a shared-link viewer, the plan only reads: it creates no metric and doesn't keep
    one in use."""
    if team.parent_team_id is not None:
        return "precomputing is not available in a child environment"
    expr = fill_range_variables(text, date_from, date_to)
    query = parse_promql(expr)
    if isinstance(query, str):
        return query
    resolved = _resolve_interval(date_from, date_to, interval)
    step = _interval_step(resolved)
    first_step = _align_to_interval(date_from, resolved, tzinfo=team.timezone_info)
    window = query.window or step
    bucket = bucket_for(team, query)
    if not (_on_boundary(step, bucket) and _on_boundary(window, bucket) and _on_boundary(first_step, bucket)):
        return f"the step and window are not whole {int(bucket / HOUR)}-hour buckets"
    leaf = leaf_for_promql(query, bucket)
    precomputed_metric = find_precomputed_metric(team.pk, leaf)
    if precomputed_metric is None:
        if date_to - date_from < MIN_RANGE_TO_CREATE:
            return "the range is too short to precompute"
        if not record_use:
            return NOT_STARTED_BY_VIEWER
        if get_or_create_precomputed_metric(team.pk, leaf) is None:
            return "the project has no room for another precomputed metric"
        return "precomputing started"
    if precomputed_metric.state != MetricPrecomputedMetric.State.ACTIVE:
        return "the precomputed metric is paused"
    if record_use:
        _touch(precomputed_metric)
    covered_from, covered_to = precomputed_metric.covered_from, precomputed_metric.covered_to
    if covered_from is None or covered_to is None or covered_from > first_step - window:
        return "the precomputed metric is still filling"
    if date_to - covered_to > MAX_RAW_TAIL:
        return "the precomputed metric is behind"
    last_step = first_step + (date_to - first_step) // step * step
    return PromQLPlan(
        query=query,
        precomputed_metric=precomputed_metric,
        expr=expr,
        first_step=first_step,
        step=step,
        window=window,
        cut=min(covered_to, last_step),
        last_step=last_step,
    )


def _touch(precomputed_metric: MetricPrecomputedMetric) -> None:
    now = timezone.now()
    if precomputed_metric.last_used_at < now - _LAST_USED_RESOLUTION:
        MetricPrecomputedMetric.objects.for_team(precomputed_metric.team_id).filter(pk=precomputed_metric.pk).update(
            last_used_at=now
        )


def read_promql_entries(plan: PromQLPlan) -> dict[EntryKey, Entry]:
    """The stored buckets that the planned steps read. Raises `TooManyStoredPointsError` past `MAX_STORED_POINTS`."""
    return read_entries(plan.precomputed_metric, plan.first_step - plan.window, plan.cut, max_points=MAX_STORED_POINTS)


def read_raw_tail_entries(team: Team, plan: PromQLPlan) -> dict[EntryKey, Entry]:
    """The buckets from `cut` to the last step, from Snuffle with the fill's query. The caller records the query."""
    if plan.cut >= plan.last_step:
        return {}
    return query_promql_buckets(team, plan.precomputed_metric, plan.cut, plan.last_step)


def _steps(plan: PromQLPlan) -> Iterator[dt.datetime]:
    step = plan.first_step
    while step <= plan.last_step:
        yield step
        step += plan.step


def _windows(plan: PromQLPlan, bucket: dt.timedelta) -> dict[dt.datetime, list[dt.datetime]]:
    """Each bucket start, and the steps whose window `(t - w, t]` holds the bucket `(b, b + R]`."""
    steps_by_bucket: dict[dt.datetime, list[dt.datetime]] = {}
    for step in _steps(plan):
        bucket_start = step - plan.window
        while bucket_start < step:
            steps_by_bucket.setdefault(bucket_start, []).append(step)
            bucket_start += bucket
    return steps_by_bucket


def histogram_quantile(quantile: float, buckets: Sequence[tuple[float, float]]) -> float:
    """Prometheus' `histogram_quantile` over `(upper bound, cumulative count)` pairs."""
    if math.isnan(quantile):
        return math.nan
    if quantile < 0:
        return -math.inf
    if quantile > 1:
        return math.inf
    merged: dict[float, float] = {}
    for upper, count in buckets:
        merged[upper] = merged.get(upper, 0.0) + count
    ordered = sorted(merged.items())
    if len(ordered) < 2 or not math.isinf(ordered[-1][0]):
        return math.nan
    monotonic, highest = [], -math.inf
    for upper, count in ordered:
        highest = max(highest, count)
        monotonic.append((upper, highest))
    observations = monotonic[-1][1]
    if observations == 0:
        return math.nan
    rank = quantile * observations
    index = next(position for position, (_, count) in enumerate(monotonic) if count >= rank)
    if index == len(monotonic) - 1:
        return monotonic[-2][0]
    if index == 0 and monotonic[0][0] <= 0:
        return monotonic[0][0]
    bucket_start, bucket_end, count = 0.0, monotonic[index][0], monotonic[index][1]
    if index > 0:
        bucket_start = monotonic[index - 1][0]
        count -= monotonic[index - 1][1]
        rank -= monotonic[index - 1][1]
    if count == 0:
        # Only an empty first bucket with a zero rank gets here. Prometheus divides 0 by 0 and returns NaN.
        return math.nan
    return bucket_start + (bucket_end - bucket_start) * (rank / count)


def _output_labels(labels: dict[str, str]) -> dict[str, str]:
    # Prometheus drops a label whose value is empty.
    return {key: value for key, value in labels.items() if value}


def evaluate_stored(plan: PromQLPlan, entries: dict[EntryKey, Entry]) -> list[dict[str, Any]]:
    """The planned steps from stored and raw tail buckets, shaped like Snuffle's `matrix` results."""
    query = plan.query
    kept = [label.key for label in labels_of(plan.precomputed_metric)]
    bucket = bucket_width(plan.precomputed_metric)
    steps_by_bucket = _windows(plan, bucket)
    quantile = query.kind == PrecomputedMetricKind.BUCKET_INCREASE
    # A quantile folds `le` into its value. Any other query keeps `le` like any other label.
    output_by = [label for label in query.group_by if label != "le"] if quantile else list(query.group_by)
    sums: dict[tuple[dt.datetime, tuple[str, ...], str], float] = {}
    expanded = 0
    for entry in entries.values():
        values = dict(zip(kept, entry.labels))
        if not all(matcher.matches(values.get(matcher.label, "")) for matcher in query.matchers):
            continue
        group = tuple(values.get(label, "") for label in output_by)
        le = values.get("le", "") if quantile else ""
        for bucket_start, value in entry.points.items():
            steps = steps_by_bucket.get(bucket_start, ())
            expanded += len(steps)
            if expanded > MAX_EXPANDED_POINTS:
                raise TooManyStoredPointsError
            for step in steps:
                key = (step, group, le)
                sums[key] = sums.get(key, 0.0) + float(value)  # type: ignore[arg-type]

    by_group: dict[tuple[str, ...], dict[dt.datetime, float]] = {}
    if quantile:
        buckets: dict[tuple[dt.datetime, tuple[str, ...]], list[tuple[float, float]]] = {}
        for (step, group, le), total in sums.items():
            try:
                upper = float(le)
            except ValueError:
                continue
            buckets.setdefault((step, group), []).append((upper, total))
        for (step, group), pairs in buckets.items():
            assert query.quantile is not None
            by_group.setdefault(group, {})[step] = histogram_quantile(query.quantile, pairs)
    else:
        for (step, group, _), total in sums.items():
            by_group.setdefault(group, {})[step] = total

    if query.rank is not None and query.k is not None:
        by_group = _rank(by_group, query.rank, query.k)
    return [
        {
            "metric": _output_labels(dict(zip(output_by, group))),
            "values": [[step.timestamp(), value] for step, value in sorted(points.items())],
        }
        for group, points in by_group.items()
        if points
    ]


def _rank(by_group: dict[tuple[str, ...], dict[dt.datetime, float]], rank: str, k: int) -> dict:
    """`topk` or `bottomk` at each step: a group keeps only the steps where it ranks in the first `k`."""
    present_by_step: dict[dt.datetime, list[tuple[float, tuple[str, ...]]]] = {}
    for group, points in by_group.items():
        for step, value in points.items():
            present_by_step.setdefault(step, []).append((value, group))
    kept: dict[tuple[str, ...], dict[dt.datetime, float]] = {}
    for step, present in present_by_step.items():
        present.sort(key=lambda item: item[0], reverse=rank == "topk")
        for value, group in present[:k]:
            kept.setdefault(group, {})[step] = value
    return kept
