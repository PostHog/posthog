from __future__ import annotations

import threading
from collections import defaultdict

from prometheus_client import Gauge


class TopKCounter:
    """
    A counter that only exports the top K label values to Prometheus.

    Tracks all values in-memory but only exports the top K by value to avoid
    cardinality explosion with high-cardinality labels.

    Usage:
        top_teams = TopKCounter(
            name="llm_gateway_cost_by_team_usd",
            documentation="Cost in USD by team (top K only)",
            k=100,
        )
        top_teams.inc("team_123", 0.05)
    """

    def __init__(self, name: str, documentation: str, k: int = 100):
        self._name = name
        self._k = k
        self._values: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()
        self._exported_labels: set[str] = set()
        self._gauge = Gauge(name, documentation, labelnames=["label"])

    def inc(self, label: str | int | None, value: float = 1.0) -> None:
        if label is None or value <= 0:
            return

        label_str = str(label)

        with self._lock:
            self._values[label_str] += value
            self._update_exported(label_str)

    def _update_exported(self, label: str) -> None:
        if label in self._exported_labels:
            self._gauge.labels(label=label).set(self._values[label])
            return

        if len(self._exported_labels) < self._k:
            self._exported_labels.add(label)
            self._gauge.labels(label=label).set(self._values[label])
            return

        min_label = min(self._exported_labels, key=lambda x: self._values[x])
        if self._values[label] > self._values[min_label]:
            try:
                self._gauge.remove(min_label)
            except KeyError:
                pass
            self._exported_labels.discard(min_label)
            self._exported_labels.add(label)
            self._gauge.labels(label=label).set(self._values[label])

    def get(self, label: str) -> float:
        return self._values.get(label, 0.0)
