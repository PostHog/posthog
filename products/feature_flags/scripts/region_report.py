"""Compare feature flag definitions between PostHog's US and EU dogfood projects.

PostHog dogfoods its own feature flags to control the product for itself: those
flags live in project (team) 2 on prod-us and project (team) 1 on prod-eu - two
separate PostHog Cloud accounts. Flags never sync automatically between them,
which means the two flag sets can drift silently: a flag present in one region
and missing in the other, or rolled out to a different percentage than its
counterpart.

Source-agnostic: this module only knows about flag dicts (`key`, `name`, `active`,
`archived`, `filters`) and doesn't care how they were fetched. The
`flags:compare-regions` hogli command (`tools/hogli-commands/hogli_commands/flags.py`)
fetches them from each region's app Postgres via Metabase and calls into this module
for the diffing and reporting.

`max_rollout_percentage` is the same metric used by the flag-status endpoint (see
`FeatureFlagStatusChecker.get_rollout_summary` in
`products/feature_flags/backend/flag_status.py`): the highest `rollout_percentage`
across the flag's release condition groups, treating a missing value as 100 (its
runtime default).
"""

# ruff: noqa: T201 allow print statements in this CLI reporting module

from __future__ import annotations

import sys
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class FlagSummary:
    key: str
    name: str
    active: bool
    archived: bool
    max_rollout_percentage: Optional[int]
    is_multivariate: bool


def max_rollout_percentage(filters: dict[str, Any]) -> Optional[int]:
    """Highest rollout_percentage across a flag's release condition groups.

    None if the flag has no groups. A missing rollout_percentage on a group evaluates
    to 100% at runtime, so it counts as 100 here - mirroring
    FeatureFlagStatusChecker.get_rollout_summary in products/feature_flags/backend/flag_status.py.
    """
    groups = filters.get("groups") or []
    result: Optional[int] = None
    for group in groups:
        percentage = group.get("rollout_percentage")
        percentage = 100 if percentage is None else percentage
        result = percentage if result is None else max(result, percentage)
    return result


def summarize_flag(flag: dict[str, Any]) -> FlagSummary:
    filters = flag.get("filters") or {}
    multivariate = filters.get("multivariate")
    return FlagSummary(
        key=flag["key"],
        name=flag.get("name") or "",
        active=bool(flag.get("active")),
        archived=bool(flag.get("archived")),
        max_rollout_percentage=max_rollout_percentage(filters),
        is_multivariate=bool(multivariate and multivariate.get("variants")),
    )


def diff_flags(
    us_flags: dict[str, FlagSummary], eu_flags: dict[str, FlagSummary]
) -> tuple[dict[str, FlagSummary], dict[str, FlagSummary], list[tuple[str, FlagSummary, FlagSummary]]]:
    """Split two regions' flag sets into US-only, EU-only, and differing-in-common flags."""
    only_us = {key: summary for key, summary in us_flags.items() if key not in eu_flags}
    only_eu = {key: summary for key, summary in eu_flags.items() if key not in us_flags}
    differences = [
        (key, us_flags[key], eu_flags[key])
        for key in sorted(us_flags.keys() & eu_flags.keys())
        if us_flags[key].active != eu_flags[key].active
        or us_flags[key].max_rollout_percentage != eu_flags[key].max_rollout_percentage
    ]
    return only_us, only_eu, differences


def format_pct(value: Optional[int]) -> str:
    return "N/A" if value is None else f"{value}%"


def _sorted_by_key(flags: dict[str, FlagSummary]) -> list[FlagSummary]:
    return sorted(flags.values(), key=lambda f: f.key)


def print_section(
    title: str, count: int, columns: list[tuple[str, int]], rows: list[list[str]], *, markdown: bool
) -> None:
    labels = [label for label, _ in columns]
    if markdown:
        print(f"\n### {title} ({count})\n")
        if not rows:
            print("_(none)_")
            return
        print(_format_markdown_row(labels))
        print(_format_markdown_row(["---"] * len(labels)))
        for row in rows:
            print(_format_markdown_row(row))
        return

    print(f"\n=== {title} ({count}) ===")
    if not rows:
        print("(none)")
        return
    widths = [width for _, width in columns]
    print(_format_columns(labels, widths))
    for row in rows:
        print(_format_columns(row, widths))


def _format_columns(values: list[str], widths: list[int]) -> str:
    return " ".join(f"{value[:width]:<{width}}" for value, width in zip(values, widths))


def _format_markdown_row(values: list[str]) -> str:
    escaped = [value.replace("|", "\\|") for value in values]
    return "| " + " | ".join(escaped) + " |"


_FLAG_ONLY_COLUMNS = [("key", 45), ("name", 30), ("active", 7), ("rollout", 8)]
_DIFFERENCES_COLUMNS = [("key", 45), ("US active", 10), ("US rollout", 11), ("EU active", 10), ("EU rollout", 11)]


def print_flag_only_section(title: str, flags: dict[str, FlagSummary], *, markdown: bool = False) -> None:
    rows = [
        [summary.key, summary.name, str(summary.active), format_pct(summary.max_rollout_percentage)]
        for summary in _sorted_by_key(flags)
    ]
    print_section(title, len(flags), _FLAG_ONLY_COLUMNS, rows, markdown=markdown)


def print_differences_section(
    differences: list[tuple[str, FlagSummary, FlagSummary]], *, markdown: bool = False
) -> None:
    rows = [
        [
            key,
            str(us.active),
            format_pct(us.max_rollout_percentage),
            str(eu.active),
            format_pct(eu.max_rollout_percentage),
        ]
        for key, us, eu in differences
    ]
    print_section(
        "Flags in both regions with different active state or rollout percentage",
        len(differences),
        _DIFFERENCES_COLUMNS,
        rows,
        markdown=markdown,
    )


def write_json_report(
    path: str,
    only_us: dict[str, FlagSummary],
    only_eu: dict[str, FlagSummary],
    differences: list[tuple[str, FlagSummary, FlagSummary]],
) -> None:
    report = {
        "only_in_us": [asdict(summary) for summary in _sorted_by_key(only_us)],
        "only_in_eu": [asdict(summary) for summary in _sorted_by_key(only_eu)],
        "differences": [{"key": key, "us": asdict(us), "eu": asdict(eu)} for key, us, eu in differences],
    }
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote full report to {path}", file=sys.stderr)
