"""The metric names of a team, so the import can check a name and suggest close matches."""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Iterable

from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.facade.contracts import MAX_SPARKLINE_BATCH_SIZE
from products.metrics.backend.metric_names_query_runner import MetricNamesQueryRunner

CATALOG_LOOKBACK = dt.timedelta(days=7)
CATALOG_LIMIT = 1000
HISTOGRAM_TYPES = frozenset({"histogram", "exponential_histogram"})
# Prometheus names the series of one histogram or summary with these suffixes. The metric stores one name.
_SERIES_SUFFIXES = ("_bucket", "_sum", "_count")
_IGNORED_TOKENS = frozenset({"total", "seconds", "second", "ms", "milliseconds", "bytes", "bucket", "sum", "count"})
_MIN_SUGGESTION_SCORE = 0.34


@frozen
class CatalogEntry:
    name: str
    metric_type: str
    unit: str


def _base_name(name: str) -> str | None:
    for suffix in _SERIES_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return None


def _tokens(name: str) -> frozenset[str]:
    return frozenset(token for token in re.split(r"[._\-:/]+", name.lower()) if token and token not in _IGNORED_TOKENS)


class MetricCatalog:
    def __init__(self, entries: Iterable[CatalogEntry], *, complete: bool) -> None:
        self._entries = {entry.name: entry for entry in entries}
        self._complete = complete
        self._looked_up: set[str] = set()

    @classmethod
    def load(cls, team: Team) -> MetricCatalog:
        rows = MetricNamesQueryRunner(
            team=team, limit=CATALOG_LIMIT, lookback=CATALOG_LOOKBACK, include_sparklines=False
        ).run()
        return cls((_entry(row) for row in rows), complete=len(rows) < CATALOG_LIMIT)

    def look_up(self, team: Team, names: Iterable[str]) -> None:
        """Fetch names that a truncated catalog does not hold, in batches that the names query accepts."""
        if self._complete:
            return
        wanted: list[str] = []
        for name in dict.fromkeys(names):
            for candidate in (name, _base_name(name)):
                if candidate and candidate not in self._entries and candidate not in self._looked_up:
                    wanted.append(candidate)
        wanted = list(dict.fromkeys(wanted))
        for start in range(0, len(wanted), MAX_SPARKLINE_BATCH_SIZE):
            batch = wanted[start : start + MAX_SPARKLINE_BATCH_SIZE]
            rows = MetricNamesQueryRunner(
                team=team, names=batch, limit=len(batch), lookback=CATALOG_LOOKBACK, include_sparklines=False
            ).run()
            self._entries.update((row["name"], _entry(row)) for row in rows)
        self._looked_up.update(wanted)

    def resolve(self, name: str) -> CatalogEntry | None:
        if entry := self._entries.get(name):
            return entry
        base = _base_name(name)
        entry = self._entries.get(base) if base else None
        if entry is not None and (entry.metric_type in HISTOGRAM_TYPES or entry.metric_type == "summary"):
            return entry
        return None

    def suggestions(self, name: str, *, limit: int = 5) -> list[str]:
        wanted = _tokens(name)
        if not wanted:
            return []
        scored: list[tuple[float, str]] = []
        for candidate in self._entries:
            tokens = _tokens(candidate)
            if not tokens:
                continue
            score = len(wanted & tokens) / len(wanted | tokens)
            if score >= _MIN_SUGGESTION_SCORE:
                scored.append((score, candidate))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [candidate for _, candidate in scored[:limit]]

    def entries(self, *, limit: int) -> list[CatalogEntry]:
        return sorted(self._entries.values(), key=lambda entry: entry.name)[:limit]

    @property
    def complete(self) -> bool:
        return self._complete


def _entry(row: dict[str, object]) -> CatalogEntry:
    return CatalogEntry(
        name=str(row["name"]), metric_type=str(row.get("metric_type") or ""), unit=str(row.get("unit") or "")
    )
