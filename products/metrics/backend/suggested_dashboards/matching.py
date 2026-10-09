"""Compares the panels of a template with the metric names of a team."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.metrics.backend.dashboard_import.catalog import CatalogEntry, MetricCatalog
from products.metrics.backend.dashboard_import.promql_text import metric_names as promql_metric_names
from products.metrics.backend.suggested_dashboards.spec import TemplatePanel

# A template is a candidate when at least this share of its panels would show data.
MIN_CANDIDATE_COVERAGE = 0.34
# Without an AI evaluation, a template is suggested only when most of its panels would show data.
MIN_SUGGESTION_COVERAGE = 0.6
MIN_SUPPORTED_PANELS = 2
MIN_FAMILY_SIZE = 3
_TOKEN_SPLIT = re.compile(r"[._:/\-]+")


def query_metric_names(query: dict[str, Any] | None) -> list[str]:
    """The metric names that one insight query reads."""
    if not query:
        return []
    if query.get("kind") == "MetricsHistogramQuery":
        name = query.get("metricName")
        return [name] if isinstance(name, str) and name else []
    names: list[str] = []
    if query.get("language") == "promql" and isinstance(query.get("promql"), str):
        names.extend(promql_metric_names(query["promql"]))
    for clause in query.get("clauses") or []:
        name = clause.get("metricName") if isinstance(clause, dict) else None
        if isinstance(name, str) and name:
            names.append(name)
    return list(dict.fromkeys(names))


def template_metric_names(panels: Iterable[TemplatePanel]) -> list[str]:
    names: list[str] = []
    for panel in panels:
        names.extend(query_metric_names(panel.query))
    return sorted(set(names))


@frozen
class TemplateMatch:
    template_key: str
    panel_count: int
    supported_panel_count: int
    matched_metric_names: tuple[str, ...]
    missing_metric_names: tuple[str, ...]

    @property
    def coverage(self) -> float:
        return self.supported_panel_count / self.panel_count if self.panel_count else 0.0

    @property
    def is_candidate(self) -> bool:
        return self.supported_panel_count >= MIN_SUPPORTED_PANELS and self.coverage >= MIN_CANDIDATE_COVERAGE

    @property
    def is_strong(self) -> bool:
        return self.supported_panel_count >= MIN_SUPPORTED_PANELS and self.coverage >= MIN_SUGGESTION_COVERAGE


def match_template(template_key: str, panels: Sequence[TemplatePanel], catalog: MetricCatalog) -> TemplateMatch:
    """A panel is supported when the team sends every metric it reads."""
    query_panels = [panel for panel in panels if panel.query]
    matched: set[str] = set()
    missing: set[str] = set()
    supported = 0
    for panel in query_panels:
        names = query_metric_names(panel.query)
        found = [name for name in names if catalog.resolve(name) is not None]
        matched.update(found)
        missing.update(name for name in names if name not in found)
        if names and len(found) == len(names):
            supported += 1
    return TemplateMatch(
        template_key=template_key,
        panel_count=len(query_panels),
        supported_panel_count=supported,
        matched_metric_names=tuple(sorted(matched)),
        missing_metric_names=tuple(sorted(missing)),
    )


@frozen
class MetricFamily:
    prefix: str
    entries: tuple[CatalogEntry, ...]


def _prefix(name: str, depth: int) -> str:
    tokens = [token for token in _TOKEN_SPLIT.split(name.lower()) if token]
    return "_".join(tokens[:depth]) if tokens else name


def metric_families(entries: Iterable[CatalogEntry], *, max_family_size: int = 40) -> list[MetricFamily]:
    """Group metric names by their leading words, so that a prompt reads them as groups and not as one long list.

    A family that is too large splits on its second word. Names in families smaller than `MIN_FAMILY_SIZE`
    go to one family with the prefix `other`.
    """
    groups: dict[str, list[CatalogEntry]] = defaultdict(list)
    for entry in entries:
        groups[_prefix(entry.name, 1)].append(entry)
    families: list[MetricFamily] = []
    rest: list[CatalogEntry] = []
    for prefix, members in sorted(groups.items()):
        if len(members) > max_family_size:
            split: dict[str, list[CatalogEntry]] = defaultdict(list)
            for entry in members:
                split[_prefix(entry.name, 2)].append(entry)
            for sub_prefix, sub_members in sorted(split.items()):
                if len(sub_members) >= MIN_FAMILY_SIZE:
                    families.append(MetricFamily(prefix=sub_prefix, entries=tuple(sub_members)))
                else:
                    rest.extend(sub_members)
        elif len(members) >= MIN_FAMILY_SIZE:
            families.append(MetricFamily(prefix=prefix, entries=tuple(members)))
        else:
            rest.extend(members)
    if rest:
        families.append(MetricFamily(prefix="other", entries=tuple(sorted(rest, key=lambda entry: entry.name))))
    return families
