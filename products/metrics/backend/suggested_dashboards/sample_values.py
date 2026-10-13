"""Made-up but plausible results for template panels whose metrics a project does not send.

A reviewer can then see how a dashboard looks without the metrics. The values only depend on the panel query,
so they are the same on every load, and nothing is written to the project.
"""

from __future__ import annotations

import re
import math
import random
import hashlib
import datetime as dt
from collections.abc import Sequence
from typing import Any, NamedTuple

from posthog.schema import MetricsHistogramQueryResponse, MetricsQueryPoint, MetricsQueryResponse, MetricsQuerySeries

from products.metrics.backend.formula import evaluate, parse_formula
from products.metrics.backend.metric_query_runner import _INTERVAL_LADDER, _pick_interval
from products.metrics.backend.suggested_dashboards.matching import query_metric_names

DAY = 86_400.0
WINDOW = dt.timedelta(hours=24)
MAX_SERIES = 4
_VOLUME_WEIGHTS = (1.0, 0.55, 0.3, 0.15)
# Latencies and levels of different series are close to each other, unlike their volumes.
_LEVEL_WEIGHTS = (1.0, 1.3, 0.8, 1.6)
_ERROR_WORDS = frozenset({"error", "errors", "fail", "failed", "failure", "failures", "miss", "misses", "drop"})
_ERROR_WORDS |= {"dropped", "retry", "retries", "reject", "rejected", "timeout", "timeouts", "restarts", "panic"}
_ERROR_WORDS |= {"rollback", "rollbacks", "deadlock", "deadlocks"}
_LARGE_WORDS = frozenset({"total", "size", "limit", "capacity", "max"})
_PART_WORDS = frozenset({"used", "usage", "available", "avail", "free"})
_STATE_WORDS = frozenset({"up", "ready", "healthy", "available", "alive"})
_FEW_WORDS = frozenset({"replicas", "brokers", "nodes", "instances", "workers", "servers"})
_RATIO_WORDS = frozenset({"ratio", "utilization", "utilisation", "percent", "fraction", "usage"})
_SECONDS_WORDS = frozenset({"seconds", "duration", "latency", "time"})
# Label values for common attribute keys, with the share of traffic of each.
_LABELS: tuple[tuple[frozenset[str], tuple[str, ...], tuple[float, ...] | None], ...] = (
    (frozenset({"status", "code"}), ("200", "404", "500"), (1.0, 0.06, 0.02)),
    (frozenset({"class"}), ("2", "4", "5"), (1.0, 0.06, 0.02)),
    (frozenset({"method"}), ("GET", "POST", "PUT"), (1.0, 0.4, 0.1)),
    (frozenset({"phase"}), ("Running", "Pending", "Failed"), (1.0, 0.05, 0.02)),
    (
        frozenset({"route", "path", "endpoint", "handler"}),
        ("/api/orders", "/api/users", "/api/search", "/health"),
        None,
    ),
    (frozenset({"service", "job", "app", "application"}), ("api", "web", "worker", "billing"), None),
    (frozenset({"namespace"}), ("default", "payments", "monitoring"), None),
    (frozenset({"topic"}), ("orders", "payments", "events"), None),
    (frozenset({"consumergroup", "group"}), ("orders-consumer", "payments-consumer", "analytics"), None),
    (frozenset({"datname", "database"}), ("app", "analytics", "postgres"), None),
    (frozenset({"region"}), ("us-east-1", "eu-west-1", "ap-south-1"), None),
    (frozenset({"kind"}), ("minor", "major", "incremental"), None),
    (frozenset({"space"}), ("new_space", "old_space", "code_space"), None),
    (frozenset({"mountpoint"}), ("/", "/var", "/data"), None),
)
_SECONDS_BOUNDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_COUNT_BOUNDS = (1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0)


class _Level(NamedTuple):
    value: float
    whole: bool = False
    # A state such as up or ready is 1, so it does not wave.
    steady: bool = False


def _words(text: str) -> frozenset[str]:
    # Splits snake_case, dotted and camelCase names, such as node_memory_MemTotal_bytes.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return frozenset(word for word in re.split(r"[^a-z0-9]+", spaced.lower()) if word)


def _seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256("\x1f".join(map(str, parts)).encode()).digest()[:8], "big")


def _unit(query: dict[str, Any]) -> str:
    return str((query.get("display") or {}).get("unit") or query.get("unit") or "")


def _grid(now: dt.datetime) -> list[dt.datetime]:
    date_from = now - WINDOW
    step = next(step for name, step, _ in _INTERVAL_LADDER if name == _pick_interval(date_from, now))
    start = dt.datetime.fromtimestamp(
        math.ceil(date_from.timestamp() / step.total_seconds()) * step.total_seconds(), tz=dt.UTC
    )
    return [start + step * index for index in range(int((now - start) / step) + 1)]


def _is_error(clause: dict[str, Any]) -> bool:
    words = _words(str(clause.get("metricName") or ""))
    for item in clause.get("filters") or []:
        value = str(item.get("value") or "")
        words |= _words(value)
        # A status class or code that starts with 5, such as 5, 5xx or 503.
        if re.fullmatch(r"5(xx|\d\d)?", value.lower()):
            return True
    return bool(words & _ERROR_WORDS)


def _level(clause: dict[str, Any], unit: str) -> _Level:
    """The typical value of one series of the clause."""
    name = str(clause.get("metricName") or "")
    words = _words(name)
    aggregation = str(clause.get("aggregation") or "")
    # The metric name tells apart two values of a formula, such as available and total bytes.
    jitter = 0.9 + 0.2 * random.Random(_seed(name)).random()
    if aggregation in ("histogram_quantile", "quantile", "p95"):
        quantile = float(clause.get("quantile") or 0.95)
        factor = 3.0 if quantile >= 0.99 else 2.2 if quantile >= 0.95 else 1.8 if quantile >= 0.9 else 1.0
        return _Level(0.08 * factor * jitter * (1000 if unit == "ms" else 1))
    error = _is_error(clause)
    share = 0.03 if error else 0.5 if clause.get("filters") else 1.0
    # A part, such as used or free memory, is smaller than the size or the limit that it is a part of.
    large = 2.5 if words & _LARGE_WORDS and not words & _PART_WORDS else 1.0
    if aggregation == "increase":
        # An increase per bucket counts rare events, such as restarts.
        return _Level(0.6 if error else 3.0, whole=True)
    if aggregation in ("rate", "irate"):
        if "bytes" in words or unit.startswith("By"):
            level = 2.0e6
        elif "seconds" in words or "cpu" in words:
            level = 0.6
        else:
            level = 40.0
        return _Level(level * share * jitter)
    if "bytes" in words or unit.startswith("By"):
        return _Level(6.0e8 * large * share * jitter)
    if words & _SECONDS_WORDS or unit in ("s", "ms"):
        return _Level(0.12 * share * jitter * (1000 if unit == "ms" else 1))
    if words & _RATIO_WORDS:
        return _Level((55.0 if unit == "%" else 0.55) * share * jitter)
    if words & _FEW_WORDS:
        return _Level(4.0 * share * large, whole=True)
    if words & _STATE_WORDS:
        return _Level(1.0, whole=True, steady=True)
    # node_load1, node_load5 and node_load15 are run queue lengths, close to the number of cores.
    if any(word.startswith("load") for word in words):
        return _Level(1.5 * jitter)
    return _Level(60.0 * share * jitter * large, whole=True)


def _label_values(key: str, metric_name: str) -> tuple[tuple[str, ...], tuple[float, ...] | None]:
    words = _words(key)
    if "mode" in words:
        metric = _words(metric_name)
        if "cpu" in metric:
            return ("idle", "user", "system", "iowait"), (1.0, 0.25, 0.1, 0.03)
        if words & {"lock", "locks"} or metric & {"lock", "locks"}:
            return ("AccessShareLock", "RowExclusiveLock", "ExclusiveLock"), (1.0, 0.3, 0.05)
    for keys, values, weights in _LABELS:
        if words & keys:
            return values, weights
    tail = re.split(r"[^a-zA-Z0-9]+", key.strip("._- "))[-1] or "value"
    return tuple(f"{tail}-{index + 1}" for index in range(3)), None


def _label_sets(clause: dict[str, Any], *, volume: bool) -> list[tuple[dict[str, str], float]]:
    keys = [str(item.get("key")) for item in clause.get("groupBy") or [] if item.get("key")]
    sets: list[tuple[dict[str, str], float]] = [({}, 1.0)]
    for key in keys:
        values, weights = _label_values(key, str(clause.get("metricName") or ""))
        shares = weights if weights and volume else (_VOLUME_WEIGHTS if volume else _LEVEL_WEIGHTS)
        sets = [
            ({**labels, key: value}, share * shares[index % len(shares)])
            for labels, share in sets
            for index, value in enumerate(values)
        ][:MAX_SERIES]
    return sets


def _values(level: float, whole: bool, times: Sequence[dt.datetime], *seed: object) -> list[float]:
    """A daily wave with a little noise around the level."""
    phase = random.Random(_seed(*seed)).random() * 2 * math.pi
    values = []
    for time in times:
        wave = 1 + 0.25 * math.sin(2 * math.pi * time.timestamp() / DAY + phase)
        # Noise seeded by the bucket, so a point keeps its value when the window moves on.
        noise = random.Random(_seed(*seed, int(time.timestamp()))).gauss(0, 1)
        value = max(level * wave * (1 + 0.05 * noise), 0.0)
        values.append(float(round(value)) if whole else value)
    return values


def _clause_values(
    clause: dict[str, Any], unit: str, times: Sequence[dt.datetime]
) -> list[tuple[dict[str, str], list[float]]]:
    level = _level(clause, unit)
    aggregation = str(clause.get("aggregation") or "")
    if level.steady:
        return [(labels, [1.0] * len(times)) for labels, _ in _label_sets(clause, volume=False)]
    value, whole = level.value, level.whole
    volume = aggregation in ("rate", "increase", "irate", "sum")
    return [
        (
            labels,
            # The aggregation and quantile are in the seed, so that p50 and p99 of one metric do not move in step.
            _values(
                value * share,
                whole,
                times,
                clause.get("metricName"),
                aggregation,
                clause.get("quantile"),
                sorted(labels.items()),
            ),
        )
        for labels, share in _label_sets(clause, volume=volume)
    ]


def _series_response(query: dict[str, Any], times: list[dt.datetime]) -> dict[str, Any]:
    unit = _unit(query)
    stamps = [time.isoformat() for time in times]
    clauses = list(query.get("clauses") or [])
    if query.get("language") in ("promql", "sql"):
        names = sorted(query_metric_names(query))
        clauses = [{"name": "a", "metricName": names[0], "aggregation": "avg"}] if names else []
    by_clause = {str(clause.get("name")): _clause_values(clause, unit, times) for clause in clauses}
    series: list[MetricsQuerySeries] = []
    formula = query.get("formula")
    if formula and by_clause:
        node = parse_formula(formula, frozenset(by_clause))
        first = next(iter(by_clause.values()))
        for index, (labels, _) in enumerate(first):
            values = []
            for point in range(len(times)):
                inputs = {name: rows[min(index, len(rows) - 1)][1][point] for name, rows in by_clause.items()}
                value = max(evaluate(node, inputs), 0.0)
                values.append(min(value, 100.0) if unit == "%" else value)
            series.append(
                MetricsQuerySeries(
                    labels=labels,
                    clause="formula",
                    points=[MetricsQueryPoint(time=stamp, value=value) for stamp, value in zip(stamps, values)],
                )
            )
    else:
        for clause in clauses:
            for labels, values in by_clause[str(clause.get("name"))]:
                series.append(
                    MetricsQuerySeries(
                        labels=labels,
                        clause=str(clause.get("name")),
                        metricName=clause.get("metricName"),
                        points=[MetricsQueryPoint(time=stamp, value=value) for stamp, value in zip(stamps, values)],
                    )
                )
    return MetricsQueryResponse(results=series).model_dump(mode="json")


def _histogram_response(query: dict[str, Any], times: list[dt.datetime]) -> dict[str, Any]:
    name = str(query.get("metricName") or "")
    unit = _unit(query)
    words = _words(name)
    if unit in ("s", "ms") or words & _SECONDS_WORDS:
        bounds = [bound * (1000 if unit == "ms" else 1) for bound in _SECONDS_BOUNDS]
    elif "bytes" in words or unit.startswith("By"):
        bounds = [256.0 * 4**index for index in range(10)]
    else:
        bounds = list(_COUNT_BOUNDS)
    rng = random.Random(_seed(name, "histogram"))
    center = 3 + rng.random() * 2
    shape = [math.exp(-((row - center) ** 2) / 1.6) for row in range(len(bounds))]
    traffic = _values(400.0, False, times, name, "traffic")
    counts = [[float(round(total * weight / sum(shape))) for total in traffic] for weight in shape]
    return MetricsHistogramQueryResponse(
        results=None, bounds=bounds, counts=counts, times=[time.isoformat() for time in times]
    ).model_dump(mode="json")


def sample_response(query: dict[str, Any], *, now: dt.datetime) -> dict[str, Any]:
    """A response of the shape that the panel's query runner returns, filled with made-up values."""
    times = _grid(now)
    if query.get("kind") == "MetricsHistogramQuery":
        return _histogram_response(query, times)
    return _series_response(query, times)
