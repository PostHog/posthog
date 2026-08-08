#!/usr/bin/env python3
"""Deterministic insight title/description contradiction checker — pure stdlib.

Reads a JSON payload of saved insights on stdin and prints a JSON verdict on
stdout, so the scout can pull the corpus with one `execute-sql` over
`system.insights` and pipe it straight in. No numpy/pandas (neither is
preinstalled in the scout sandbox).

This script proposes; the scout disposes. It mechanically detects the
*contradiction shapes* that make a saved label confusing — a title that still
says "last 14 days" after the query moved to 30, a title naming an event the
series no longer tracks, a singular title over a now-multi-series query, a
"by <x>" title over a removed breakdown. Judgment calls (is this title
intentionally poetic? does the team speak a vocabulary the alias map doesn't
know?) belong to the LLM pass, so every finding carries `found` / `expected`
evidence and a confidence, and only the one shape that is ever safe to fix
without a human (a date-span token swap in the *name*) carries
`auto_fixable: true` plus a `suggested_name`.

Input shapes accepted (both the new query schema and legacy filters):

    {"insights": [ {...}, ... ]}        # or a bare [...]
    insight: {
        "short_id": "abc123",
        "name": "pageviews (last 14 days)",
        "description": "...",
        "query": {...} | "{...}" | null,     # InsightVizNode / DataVisualizationNode / ...
        "filters": {...} | "{...}" | null,   # legacy filter-based definition
    }

Output:

    {
        "checked": <int>,          # insights examined
        "skipped": [{"short_id": ..., "reason": ...}],   # findings impossible
        "findings": [
            {
                "short_id": ...,
                "name": ...,               # current name (may be "")
                "checks": [
                    {
                        "check": "date_range_mismatch",
                        "field": "name" | "description",
                        "matched": "last 14 days",     # what the label literally says
                        "expected": "last 30 days",    # what the query actually does
                        "message": "...",
                        "confidence": "high" | "medium",
                        "suggestion": "pageviews (last 30 days)",   # name field only
                    }, ...
                ],
                "suggested_name": ...,     # set when a name date-swap applies
                "auto_fixable": true,      # ONLY for a lone high-confidence name date-swap
            }, ...
        ],
    }
"""

from __future__ import annotations

import re
import sys
import json

# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

_UNIT_TO_DAYS: dict[str, float] = {
    "d": 1.0,
    "day": 1.0,
    "days": 1.0,
    "w": 7.0,
    "week": 7.0,
    "weeks": 7.0,
    "m": 30.0,
    "month": 30.0,
    "months": 30.0,
    "y": 365.0,
    "year": 365.0,
    "years": 365.0,
    "h": 1 / 24,
    "hr": 1 / 24,
    "hrs": 1 / 24,
    "hour": 1 / 24,
    "hours": 1 / 24,
}

_UNIT_WORD: dict[str, str] = {"d": "days", "w": "weeks", "m": "months", "y": "years", "h": "hours"}

# A time-window claim a human writes in a title/description: "last 14 days",
# "past 30d", "previous 2 weeks", "Last 24 Hours", or a numberless "last week".
# The understanding is always "rolling window ending now" — same semantics as a
# PostHog `-Nd` date_from. A numberless unit resolves to 1 of that unit; units
# finer than an hour ("last minute") don't get a number here by design.
_TITLE_WINDOW_RE = re.compile(
    r"\b(?P<lead>last|past|previous)\s+(?:(?P<n>\d{1,4})\s*(?:-|\s)?)?(?P<unit>days?|weeks?|months?|years?|hours?|hrs?|[dwmyh])\b",
    re.IGNORECASE,
)

# Query-side relative date_from: "-7d", "-14d", "-2w", "-24h". Anything else
# (absolute dates, "-7dStart", None) is skipped — better silent than wrong.
_QUERY_DATE_RE = re.compile(r"^-\s*(?P<n>\d{1,4})(?P<unit>[dwmyh])$")


def _normalize_label(text: str) -> str:
    """Lowercase, strip a leading '$', collapse separators."""
    return re.sub(r"[-_]+", " ", text.strip().lstrip("$").lower())


# Small, high-precision alias space: the canonical PostHog events people
# actually name insights after. A title word that resolves into one of these
# groups but matches no series event is near-certainly stale. Custom event
# names never resolve into a group, so they stay out of scope by design.
_EVENT_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "pageview": ("pageview", "pageviews", "page view", "page views"),
    "pageleave": ("pageleave", "pageleaves", "page leave", "page leaves"),
    "autocapture": ("autocapture", "autocaptured"),
    "rageclick": ("rageclick", "rageclicks", "rage click", "rage clicks"),
    "dead_click": ("deadclick", "deadclicks", "dead click", "dead clicks"),
    "exception": ("exception", "exceptions"),
    "web_vitals": ("web vitals", "web vital"),
}

# Words a "by ..." phrase follows with that mean the *interval*, not a
# breakdown property ("pageviews by day").
_INTERVAL_WORDS = {
    "day",
    "daily",
    "date",
    "week",
    "weekly",
    "month",
    "monthly",
    "hour",
    "hourly",
    "minute",
    "second",
    "quarter",
    "quarterly",
    "year",
    "yearly",
    "time",
    "of",
    "the",
    "today",
    "yesterday",
}

_BY_RE = re.compile(
    r"\b(?:broken\s+down\s+by|split\s+by|grouped\s+by|group\s+by|by)\s+(?P<prop>[a-z0-9_\$\-]+(?:\s+[a-z0-9_\$\-]+){0,2})",
    re.IGNORECASE,
)
_BY_CONNECTOR_RE = re.compile(r"\s+(?:and|or|&)\s+|,")

_VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)


def _resolve_json(raw: object) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else None
        except (ValueError, TypeError):
            return None
    return None


def _event_groups_for(text: str) -> set[str]:
    """Which alias groups a text (title or event name) resolves into."""
    norm = _normalize_label(text)
    groups = set()
    for group, aliases in _EVENT_ALIAS_GROUPS.items():
        for alias in aliases:
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", norm):
                groups.add(group)
                break
    return groups


def _extract_facts(insight: dict) -> dict:
    """Normalize an insight row into (date_from_days, series names, breakdowns, parseability)."""
    query = _resolve_json(insight.get("query"))
    filters = _resolve_json(insight.get("filters"))

    facts: dict = {
        "date_from_raw": None,
        "date_from_unit": None,
        "date_from_days": None,
        "series_names": None,  # None = unknown (not a series insight), [] = none found
        "series_count_from": None,
        "breakdowns": None,  # None = not applicable, set() = no breakdown
        "parseability": "full",  # full | hogql-skipped | legacy | unparsable
    }

    source: dict | None = None
    if query:
        source = query.get("source") if isinstance(query.get("source"), dict) else query
    if source:
        kind = source.get("kind", "")
        if kind in ("HogQLQuery", "HogQLMetadataResponse") or (
            kind in ("DataVisualizationNode", "DataTableNode") and source.get("query", {}).get("kind") == "HogQLQuery"
        ) or (kind in ("DataVisualizationNode", "DataTableNode") and "series" not in source):
            # SQL-defined insight: date range lives inside the HogQL text, not a
            # structured field. Pretending to check it would manufacture false
            # findings; record the skip instead.
            facts["parseability"] = "hogql-skipped"
            return facts

        date_range = source.get("dateRange") or {}
        date_from = date_range.get("date_from")
        series = source.get("series")
        if isinstance(series, list):
            names = []
            for node in series:
                if isinstance(node, dict):
                    name = node.get("event") or node.get("name")
                    if isinstance(name, str) and name:
                        names.append(name)
            facts["series_names"] = names
            facts["series_count_from"] = len(series)
        bf = source.get("breakdownFilter") or {}
        actual: set[str] = set()
        single = bf.get("breakdown")
        if isinstance(single, (str, int, float)):
            actual.add(_normalize_label(str(single)))
        multi = bf.get("breakdowns")
        if isinstance(multi, list):
            for entry in multi:
                prop = entry.get("property") if isinstance(entry, dict) else entry
                if isinstance(prop, (str, int, float)):
                    actual.add(_normalize_label(str(prop)))
        facts["breakdowns"] = actual if (single is not None or multi) else set()
        facts["date_from_raw"] = date_from
    elif filters:
        facts["parseability"] = "legacy"
        facts["date_from_raw"] = filters.get("date_from")
        names = []
        for node in filters.get("events") or []:
            if isinstance(node, dict) and node.get("id"):
                names.append(str(node["id"]))
        for node in filters.get("actions") or []:
            if isinstance(node, dict) and node.get("name"):
                names.append(str(node["name"]))
        facts["series_names"] = names
        facts["series_count_from"] = len(filters.get("events") or []) + len(filters.get("actions") or [])
        breakdown = filters.get("breakdown")
        if breakdown:
            actual_bd = {_normalize_label(str(b)) for b in (breakdown if isinstance(breakdown, list) else [breakdown])}
            facts["breakdowns"] = actual_bd
        else:
            facts["breakdowns"] = set()
    if not source and not filters:
        facts["parseability"] = "unparsable"

    date_from = facts["date_from_raw"]
    if isinstance(date_from, str):
        m = _QUERY_DATE_RE.match(date_from.strip())
        if m:
            facts["date_from_unit"] = m.group("unit")
            facts["date_from_days"] = _UNIT_TO_DAYS[m.group("unit")] * int(m.group("n"))

    return facts


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _canonical_phrase(n: float, unit: str) -> str:
    word = _UNIT_WORD.get(unit, "days")
    n_int = int(n)
    if n_int == 1:
        word = word[: -1] if word.endswith("s") else word
    return f"last {n_int} {word}"


def _check_date_range(label: str, field: str, facts: dict, checks: list[dict]) -> None:
    if facts["date_from_days"] is None:
        return  # absolute / unknown date_from: skip, don't guess
    actual_days = facts["date_from_days"]
    for m in _TITLE_WINDOW_RE.finditer(label):
        title_days = _UNIT_TO_DAYS.get(m.group("unit").lower())
        if title_days is None:
            continue
        title_days = title_days * int(m.group("n") or 1)
        if abs(title_days - actual_days) <= 0.01:
            continue  # agrees; "last 24 hours" vs "-1d" is fine
        qn = round(actual_days / _UNIT_TO_DAYS[facts["date_from_unit"]])
        canonical = _canonical_phrase(qn, facts["date_from_unit"])
        suggestion = label[: m.start()] + canonical + label[m.end() :]
        checks.append(
            {
                "check": "date_range_mismatch",
                "field": field,
                "matched": m.group(0),
                "expected": canonical,
                "message": (
                    f"{field} says \"{m.group(0)}\" but the query's date range is "
                    f"\"{facts['date_from_raw']}\" ({canonical})"
                ),
                "confidence": "high",
                "suggestion": suggestion if field == "name" else None,
            }
        )


def _check_events(label: str, field: str, facts: dict, checks: list[dict]) -> None:
    series = facts["series_names"]
    if series is None:
        return
    series_groups = set()
    for ev in series:
        series_groups |= _event_groups_for(ev)
    mentioned = _event_groups_for(label) - series_groups
    # Only risky when the series resolves into *some* known vocabulary that
    # disagrees — if both sides are custom-event land, say nothing.
    if mentioned and series_groups:
        for group in sorted(mentioned):
            checks.append(
                {
                    "check": "event_mismatch",
                    "field": field,
                    "matched": group.replace("_", " "),
                    "expected": ", ".join(series),
                    "message": (
                        f"{field} references \"{group.replace('_', ' ')}\" but the query's series "
                        f"tracks {series}"
                    ),
                    "confidence": "high",
                    "suggestion": None,
                }
            )


def _check_series_count(label: str, field: str, facts: dict, checks: list[dict]) -> None:
    n_series = facts["series_count_from"]
    if n_series is None:
        return
    has_multi_marker = bool(
        re.search(r"[,&/+]|\bvs\.?\b|\band\b", label, re.IGNORECASE)
    )
    if n_series >= 2 and not has_multi_marker:
        checks.append(
            {
                "check": "series_count_mismatch",
                "field": field,
                "matched": "singular phrasing",
                "expected": f"{n_series} series",
                "message": (
                    f"{field} reads like a single-metric chart but the query has "
                    f"{n_series} series — the chart no longer shows just what it says"
                ),
                "confidence": "medium",
                "suggestion": None,
            }
        )
    elif _VS_RE.search(label):
        parts = [p for p in _VS_RE.split(label) if p]
        if len(parts) >= 2 and n_series < len(parts):
            checks.append(
                {
                    "check": "series_count_mismatch",
                    "field": field,
                    "matched": f"{len(parts)} named comparisons",
                    "expected": f"{n_series} series",
                    "message": (
                        f"{field} names {len(parts)} things to compare but the query "
                        f"only has {n_series} series"
                    ),
                    "confidence": "high",
                    "suggestion": None,
                }
            )


def _check_breakdown(label: str, field: str, facts: dict, checks: list[dict]) -> None:
    breakdowns = facts["breakdowns"]
    if breakdowns is None:
        return
    m = _BY_RE.search(label)
    if not m:
        return
    raw = m.group("prop").strip()
    captured = {_normalize_label(p) for p in _BY_CONNECTOR_RE.split(raw) if p}
    captured = {p for p in captured if p and p not in _INTERVAL_WORDS}
    captured = {p for p in captured if not set(p.split()) <= _INTERVAL_WORDS}
    if not captured:
        return  # "by day" / "by week" — interval talk, not a breakdown claim
    if not breakdowns:
        checks.append(
            {
                "check": "breakdown_mismatch",
                "field": field,
                "matched": f"by {', '.join(sorted(captured))}",
                "expected": "no breakdown",
                "message": (
                    f"{field} says \"{m.group(0).strip()}\" but the query has no breakdown"
                ),
                "confidence": "high",
                "suggestion": None,
            }
        )
    elif not captured <= breakdowns:
        checks.append(
            {
                "check": "breakdown_mismatch",
                "field": field,
                "matched": f"by {', '.join(sorted(captured))}",
                "expected": f"broken down by {', '.join(sorted(breakdowns))}",
                "message": (
                    f"{field} says \"{m.group(0).strip()}\" but the query breaks down by "
                    f"{sorted(breakdowns)}"
                ),
                "confidence": "high",
                "suggestion": None,
            }
        )


_CHECKS = (_check_date_range, _check_events, _check_series_count, _check_breakdown)


def check_insight(insight: dict) -> dict | None:
    """Run every contradiction check over one insight. None = clean/unworthy."""
    name = insight.get("name") or ""
    description = insight.get("description") or ""
    facts = _extract_facts(insight)

    if facts["parseability"] == "unparsable":
        return None

    checks: list[dict] = []
    if facts["parseability"] in ("full", "legacy"):
        for check_fn in _CHECKS:
            if name:
                check_fn(name, "name", facts, checks)
            if description:
                check_fn(description, "description", facts, checks)
    # hogql-skipped: nothing checkable without parsing SQL

    if not checks:
        return None

    name_swaps = [c for c in checks if c["check"] == "date_range_mismatch" and c["field"] == "name" and c["suggestion"]]
    auto_fixable = len(checks) == 1 and bool(name_swaps)
    return {
        "short_id": insight.get("short_id"),
        "name": name,
        "checks": checks,
        "suggested_name": name_swaps[0]["suggestion"] if auto_fixable else None,
        "auto_fixable": auto_fixable,
    }


def check_insights(insights: list[dict]) -> dict:
    findings = []
    skipped = []
    checked = 0
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        facts = _extract_facts(insight)
        if facts["parseability"] in ("hogql-skipped", "unparsable"):
            skipped.append({"short_id": insight.get("short_id"), "reason": facts["parseability"]})
            continue
        checked += 1
        result = check_insight(insight)
        if result:
            findings.append(result)
    return {"checked": checked, "skipped": skipped, "findings": findings}


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {"insights": []}
    insights = payload.get("insights", payload) if isinstance(payload, dict) else payload
    if not isinstance(insights, list):
        json.dump({"error": "expected a list of insights or {'insights': [...]}"}, sys.stdout)
        sys.exit(2)
    json.dump(check_insights(insights), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
