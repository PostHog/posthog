"""A stand-in for Snuffle that answers range queries over in-memory samples with Prometheus' semantics.

It knows the shapes the precompute planner and its fills send: `sum by (G) (sum_over_time(m{M}[w]))` with
`topk`, `bottomk`, `sort` and `sort_desc`, `sum by (le, G) (increase(m_bucket{M}[w]))`, and `histogram_quantile`
over the latter. `increase` extrapolates to the window's edges as Prometheus does, so a test that compares a
planned tile with this raw answer sees the same gap a real one would.
"""

import math
import bisect
import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

from posthog.dataclasses import frozen

from products.metrics.backend.facade.enums import PrecomputedMetricKind
from products.metrics.backend.precompute.promql_plan import PromQLLeafQuery, parse_promql

_TOP_LEVEL_QUANTILE = 0.5


@frozen
class _Series:
    labels: dict[str, str]
    times: list[float]
    values: list[float]


@frozen
class _Response:
    body: dict[str, Any]
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        return self.body


class FakeSnuffle:
    def __init__(self) -> None:
        # Per series: its labels (with `__name__`), and its samples sorted by time.
        self.series: dict[tuple[tuple[str, str], ...], tuple[list[float], list[float]]] = {}
        self.queries: list[str] = []

    def add(self, name: str, labels: dict[str, str], samples: list[tuple[dt.datetime, float]]) -> None:
        key = tuple(sorted({"__name__": name, **labels}.items()))
        times, values = self.series.setdefault(key, ([], []))
        for time, value in sorted(samples):
            times.append(time.timestamp())
            values.append(value)

    def _select(self, query: PromQLLeafQuery) -> Iterator[_Series]:
        for key, (times, values) in self.series.items():
            labels = dict(key)
            if labels["__name__"] != query.metric_name:
                continue
            if all(matcher.matches(labels.get(matcher.label, "")) for matcher in query.matchers):
                yield _Series(labels=labels, times=times, values=values)

    @staticmethod
    def _window(series: _Series, start: float, end: float) -> _Series:
        """The samples in `(start, end]`."""
        low, high = bisect.bisect_right(series.times, start), bisect.bisect_right(series.times, end)
        return _Series(labels=series.labels, times=series.times[low:high], values=series.values[low:high])

    @staticmethod
    def _increase(times: list[float], values: list[float], start: float, end: float) -> float | None:
        """Prometheus' `extrapolatedRate` for a counter, as `increase`."""
        if len(times) < 2:
            return None
        result = values[-1] - values[0]
        for previous, current in zip(values, values[1:]):
            if current < previous:
                result += previous
        sampled = times[-1] - times[0]
        average = sampled / (len(times) - 1)
        to_start, to_end = times[0] - start, end - times[-1]
        if result > 0 and values[0] >= 0:
            to_zero = sampled * (values[0] / result)
            to_start = min(to_start, to_zero)
        threshold = average * 1.1
        interval = sampled + (to_start if to_start < threshold else average / 2)
        interval += to_end if to_end < threshold else average / 2
        return result * interval / sampled

    @staticmethod
    def quantile(q: float, buckets: dict[float, float]) -> float:
        ordered = sorted(buckets.items())
        if len(ordered) < 2 or ordered[-1][0] != math.inf:
            return math.nan
        cumulative, highest = [], 0.0
        for upper, count in ordered:
            highest = max(highest, count)
            cumulative.append((upper, highest))
        total = cumulative[-1][1]
        if total == 0:
            return math.nan
        rank = q * total
        index = next(position for position, (_, count) in enumerate(cumulative) if count >= rank)
        upper, count = cumulative[index]
        if index == len(cumulative) - 1:
            return cumulative[-2][0]
        lower, below = (0.0, 0.0) if index == 0 else cumulative[index - 1]
        if index == 0 and upper <= 0:
            return upper
        return lower + (upper - lower) * (rank - below) / (count - below)

    def evaluate(self, expr: str, start: float, end: float, step: float) -> list[dict[str, Any]]:
        self.queries.append(expr)
        bare_increase = expr.startswith("sum") and "increase(" in expr
        parsed = parse_promql(f"histogram_quantile({_TOP_LEVEL_QUANTILE}, {expr})" if bare_increase else expr)
        assert not isinstance(parsed, str), (expr, parsed)
        window = parsed.window.total_seconds() if parsed.window is not None else step
        histogram = parsed.kind == PrecomputedMetricKind.BUCKET_INCREASE
        group_by = list(parsed.group_by)
        output_by = group_by if bare_increase or not histogram else [label for label in group_by if label != "le"]
        selected = list(self._select(parsed))
        by_group: dict[tuple[str, ...], dict[float, float]] = {}
        time = start
        while time <= end + 1e-9:
            sums: dict[tuple[str, ...], float] = {}
            for series in selected:
                inside = self._window(series, time - window, time)
                value = (
                    self._increase(inside.times, inside.values, time - window, time)
                    if histogram
                    else (math.fsum(inside.values) if inside.values else None)
                )
                if value is None:
                    continue
                group = tuple(series.labels.get(label, "") for label in group_by)
                sums[group] = sums.get(group, 0.0) + value
            if histogram and not bare_increase:
                buckets: dict[tuple[str, ...], dict[float, float]] = {}
                le_index = group_by.index("le")
                for group, total in sums.items():
                    rest = tuple(value for index, value in enumerate(group) if index != le_index)
                    buckets.setdefault(rest, {})[float(group[le_index])] = total
                assert parsed.quantile is not None
                for rest, pairs in buckets.items():
                    by_group.setdefault(rest, {})[time] = self.quantile(parsed.quantile, pairs)
            else:
                for group, total in sums.items():
                    by_group.setdefault(group, {})[time] = total
            time += step
        if parsed.rank is not None and parsed.k is not None:
            ranked: dict[tuple[str, ...], dict[float, float]] = {}
            for time in sorted({time for points in by_group.values() for time in points}):
                present = sorted(
                    ((points[time], group) for group, points in by_group.items() if time in points),
                    key=lambda item: item[0],
                    reverse=parsed.rank == "topk",
                )
                for value, group in present[: parsed.k]:
                    ranked.setdefault(group, {})[time] = value
            by_group = ranked
        return [
            {
                "metric": {label: value for label, value in zip(output_by, group) if value},
                "values": [[time, str(value)] for time, value in sorted(points.items())],
            }
            for group, points in by_group.items()
        ]

    def request(self, team_id: int, method: str, path: str, *, data: dict[str, str], **kwargs: Any) -> _Response:
        assert path == "/api/v1/query_range", path
        results = self.evaluate(data["query"], float(data["start"]), float(data["end"]), float(data["step"]))
        return _Response(body={"status": "success", "data": {"resultType": "matrix", "result": results}})


@contextmanager
def fake_snuffle(snuffle: FakeSnuffle) -> Iterator[FakeSnuffle]:
    with patch("products.metrics.backend.promql.snuffle_request", side_effect=snuffle.request):
        yield snuffle
