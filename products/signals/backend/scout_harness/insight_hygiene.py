"""Reference implementation of the insight-hygiene scout's mechanical name/description checks.

The scout (`products/signals/skills/signals-scout-insight-hygiene`) is an LLM agent and judges
every insight itself in the sandbox, so nothing at runtime imports this module — it exists to
make the mechanical core of that judgment **testable**. Its rules are written down inline in the
scout's `references/queries.md`; the scenario suite
(`products/signals/backend/test/test_insight_hygiene.py`) pins this implementation against a
corpus of confusing/clean insights and asserts the SKILL.md still encodes the same rules, so an
edit to one that forgets the other fails loudly.

Scope of the mechanical core (everything subtler stays LLM judgment):

- extract a *date-range claim* from a name/description ("last 14 days", "30d", "past week",
  "this month", ...) and compare it against the query's `dateRange.date_from`
- extract the tracked events/actions from a Trends/Stickiness/Lifecycle query (`query` JSON, or
  legacy `filters` JSON) and match natural-language event mentions in the name ("pageviews",
  "sign ups", "$pageview") against them
- detect a name that implies one series ("X" / "A vs B") while the query carries a different
  count of series
- suggest a *mechanical* new name only when the fix is replacing the stale token with the
  query-authoritative value; anything ambiguous downgrades to report-only
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_CONSECUTIVE_DIGITS_RUN = 3  # longer digit runs (2024, 404) are treated as identifiers
_FRACTION_CHARS = r",./:;"  # characters that make a digit-run read as a count, not a day count

_DECIMALISH_AROUND = re.compile(r"[\d.,]")


def _contains_long_digit_run(text: str) -> bool:
    """Whether stripped text still holds an identifier-ish digit run (years, error codes)."""
    return bool(re.search(rf"\d{{{_CONSECUTIVE_DIGITS_RUN},}}", text))


class Verdict(str, Enum):
    OK = "ok"
    STALE_DATE_RANGE = "stale_date_range"
    STALE_EVENT = "stale_event"
    SERIES_COUNT_MISMATCH = "series_count_mismatch"


class Action(str, Enum):
    NONE = "none"  # nothing wrong
    RENAME = "rename"  # mechanical fix — the scout may rename the title in place
    REPORT = "report"  # confusing, but the fix needs human judgment — list it in the report


# ---------------------------------------------------------------------------
# Date-range claims
# ---------------------------------------------------------------------------


# A claim maps a natural-language phrase to the canonical `dateRange.date_from` vocabulary the
# query uses: (days) for exact relative windows, or (unit, count) for start-anchored/relative
# non-day windows. Order matters: first match wins, most specific first.
@dataclass(frozen=True)
class DateRangeClaim:
    matched: str  # the phrase found in the name/description
    days: int | None = None  # exact relative day window (date_from "-Nd")
    unit: str | None = None  # non-day window unit: h/w/m/q/y
    count: int = 1  # window size for non-day units
    anchor: str = "relative"  # "start" (mStart-style, anchored to now) | "current" | "relative" (-NX)
    kind: str = "window"  # "window" (last 14 days) | "cadence" (weekly users)

    def canonical(self) -> str:
        """The dateRange.date_from form this claim asserts the insight uses."""
        if self.days is not None:
            return f"-{self.days}d"
        prefix = "d" if self.unit == "d" else self.unit
        if self.anchor == "current":
            return f"-0{prefix}Start"
        suffix = "Start" if self.anchor == "start" else ""
        return f"-{self.count}{prefix}{suffix}"

    @property
    def is_cadence(self) -> bool:
        """A metric-cadence claim ("weekly active users"), not a window claim — satisfied by any
        window at least as long as the cadence, and NEVER mechanically renamable."""
        return self.kind == "cadence"


_DAY_WORDS = {"one": 1, "seven": 7, "fourteen": 14, "twenty": 20, "thirty": 30, "sixty": 60, "ninety": 90}

_CLAIM_PATTERNS: list[tuple[re.Pattern[str], Any]] = [
    # "last/past N days", "N days", "Nd", "past two weeks" → exact day windows
    (
        re.compile(
            r"\b(?:last|past)\s+(\d+|one|seven|fourteen|twenty|thirty|sixty|ninety)\s+days?\b|\b(\d+)\s*-?\s*day\s+(?:window|period)\b|\b(\d{1,3})\s?d\b",
            re.I,
        ),
        lambda m: DateRangeClaim(m.group(0), days=_day_count(m)),
    ),
    (
        re.compile(r"\b(?:last|past)\s+(week|fortnight|month|quarter|year)\b", re.I),
        lambda m: DateRangeClaim(
            m.group(0),
            unit={"week": "w", "fortnight": "w", "month": "m", "quarter": "q", "year": "y"}[m.group(1).lower()],
            count=2 if m.group(1).lower() == "fortnight" else 1,
        ),
    ),
    (
        re.compile(r"\b(?:last|past)\s+(\d+)\s+(weeks?|months?|quarters?|years?|hours?)\b", re.I),
        lambda m: DateRangeClaim(
            m.group(0),
            unit={"w": "w", "m": "m", "q": "q", "y": "y", "h": "h"}[m.group(2)[0].lower()],
            count=int(m.group(1)),
        ),
    ),
    (
        re.compile(r"\b(this week|this month|this quarter|this year|today)\b", re.I),
        lambda m: {
            "today": DateRangeClaim(m.group(0), unit="d", anchor="current"),
            "this week": DateRangeClaim(m.group(0), unit="w", anchor="current"),
            "this month": DateRangeClaim(m.group(0), unit="m", anchor="current"),
            "this quarter": DateRangeClaim(m.group(0), unit="q", anchor="current"),
            "this year": DateRangeClaim(m.group(0), unit="y", anchor="current"),
        }[m.group(1).lower()],
    ),
    (
        re.compile(r"\b(weekly|monthly|daily|hourly)\s+(?:active\s+)?(?:users?|usage)\b", re.I),
        lambda m: {
            "daily": DateRangeClaim(m.group(0), days=1, kind="cadence"),
            "weekly": DateRangeClaim(m.group(0), days=7, kind="cadence"),
            "monthly": DateRangeClaim(m.group(0), days=30, kind="cadence"),
            "hourly": DateRangeClaim(m.group(0), unit="h", count=24, kind="cadence"),
        }[m.group(1).lower()],
    ),
]


def _day_count(m: re.Match[str]) -> int:
    raw = m.group(1) or m.group(2) or m.group(3)
    assert raw is not None
    if raw.isdigit():
        return int(raw)
    return _DAY_WORDS[raw.lower()]


# date_from values that mean "all time" — a name claiming a window on an all-time insight is stale.
_ALL_TIME_DATE_FROM = {"all"}


def extract_date_claim(text: str | None) -> DateRangeClaim | None:
    """The strongest date-range claim in a name/description, or None if it makes none."""
    if not text:
        return None
    for pattern, build in _CLAIM_PATTERNS:
        m = pattern.search(text)
        if m:
            return build(m)
    return None


def check_date_range(name: str | None, description: str | None, date_from: str | None) -> Verdict | None:
    """STALE_DATE_RANGE when a name/description date claim no longer matches the query's window.

    Equivalence, not string equality: "last 14 days" and `-2w` are the same window, so both sides
    compare through `parse_relative_days` whenever either form converts."""
    for text in (name, description):
        claim = extract_date_claim(text)
        if claim is None:
            continue
        # an absent window means the project default — a claimed window can be right or wrong and
        # we can't tell, so it never contradicts; only ALL-TIME contradicts a claim outright
        if date_from is None:
            continue
        if date_from in _ALL_TIME_DATE_FROM:
            return Verdict.STALE_DATE_RANGE
        if claim.canonical() == date_from:
            continue
        claim_days = claim.days if claim.days is not None else parse_relative_days(claim.canonical())
        actual_days = parse_relative_days(date_from)
        if claim_days is not None and actual_days is not None and claim_days == actual_days:
            continue
        # A cadence claim ("weekly active users") is satisfied by any window at least as long —
        # "WAU" over the last 90 days is still WAU; over the last day it isn't.
        if claim.is_cadence and claim.days is not None and actual_days is not None and actual_days >= claim.days:
            continue
        return Verdict.STALE_DATE_RANGE
    return None


def parse_relative_days(date_from: str) -> int | None:
    """Days spanned by a `-N{d|w|m|y}` date_from (rough month/year), None for anchored/ISO forms."""
    m = re.fullmatch(r"-(\d+)([dwmy])", date_from)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]


# ---------------------------------------------------------------------------
# Tracked series
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesInfo:
    kind: str  # "events" | "actions"
    name: str  # the event name / action display name
    action_id: int | None = None


# Every displayable form an event can take in an insight title. The scout renames only when a
# name token matches one of these shapes for an event the query no longer tracks.
_EVENT_DISPLAY_FORMS: dict[str, tuple[str, ...]] = {
    "$pageview": ("pageview", "pageviews", "page view", "page views", "$pageview"),
    "$pageleave": ("pageleave", "pageleaves", "page leave", "page leaves", "$pageleave"),
    "$autocapture": ("autocapture", "autocaptures", "$autocapture"),
    "$screen": ("screenview", "screenviews", "screen view", "screen views", "$screen"),
    "$rageclick": ("rageclick", "rageclicks", "rage click", "rage clicks", "$rageclick"),
    "$dead_click": ("deadclick", "deadclicks", "dead click", "dead clicks", "$dead_click"),
    "$exception": ("exception", "exceptions", "error", "errors", "$exception"),
    "$web_vitals": ("web vitals", "$web_vitals"),
}


def event_display_forms(event: str) -> tuple[str, ...]:
    """Natural-language forms of an event name that may appear in an insight title."""
    if event in _EVENT_DISPLAY_FORMS:
        return _EVENT_DISPLAY_FORMS[event]
    # Custom events: the raw name, a $-stripped form, and a humanized (spaces-for-separators) form.
    forms = {event, event.lstrip("$"), re.sub(r"[_\-\s]+", " ", event.lstrip("$")).strip()}
    return tuple(f for f in forms if f)


def normalize_event_mention(text: str, candidates_names: set[str]) -> str | None:
    """Return the event a phrase in `text` refers to, matched against `candidates_names` display
    forms; None when no candidate's form appears. Matching is word-boundary-first and favors
    longer phrases ("page views" before "views").
    """
    lowered = re.sub(r"[_\-]+", " ", text.lower())
    candidates: list[tuple[str, str]] = []  # (display form, series name)
    for name in candidates_names:
        for form in event_display_forms(name):
            candidates.append((re.sub(r"[_\-]+", " ", form.lower()), name))
    candidates.sort(key=lambda c: len(c[0]), reverse=True)
    for form, series_name in candidates:
        if not form:
            continue
        if form.startswith("$"):
            if form in lowered:
                return series_name
            continue
        if re.search(rf"(?<![\w$]){re.escape(form)}s?(?![\w])", lowered) or re.search(
            rf"(?<![\w$]){re.escape(form)}(?![\w])", lowered
        ):
            return series_name
    return None


def check_series_event(
    name: str | None,
    description: str | None,
    series: list[SeriesInfo],
    *,
    known_events: set[str] | None = None,
) -> Verdict | None:
    """STALE_EVENT when the name/description names a known-tracked event the query dropped.

    Fires only when the mentioned event resolves against `known_events` (the caller's watch
    vocabulary — the insight's own query plus prior sightings) but is absent from the query's
    current series. Unknown words never fire: with no evidence an event was ever tracked, the
    bare word "errors" in a title is a naming choice, not a staleness clue.
    """
    tracked = {s.name for s in series}
    candidates = tracked | set(known_events or set())
    for text in (name, description):
        if not text:
            continue
        mentioned = normalize_event_mention(text, candidates)
        if mentioned is not None and mentioned not in tracked:
            return Verdict.STALE_EVENT
    return None


def check_series_count(name: str | None, series: list[SeriesInfo]) -> Verdict | None:
    """SERIES_COUNT_MISMATCH for the two clear-cut shapes: an 'A vs B' name with a single series,
    or a name naming exactly one metric while the query tracks several series with no breakdown."""
    if not name:
        return None
    if re.search(r"\bvs\.?\b", name, re.I) and len(series) < 2:
        return Verdict.SERIES_COUNT_MISMATCH
    return None


# ---------------------------------------------------------------------------
# Query formats
# ---------------------------------------------------------------------------


def extract_series(query_json: dict[str, Any] | None, legacy_filters: dict[str, Any] | None) -> list[SeriesInfo]:
    """Series for trend-family queries (TrendsQuery/StickinessQuery/LifecycleQuery or legacy
    filter insights). Funnels/retention/paths return empty — their names describe flows, and this
    detector deliberately stays out of flow-land (the scout's LLM judgment still applies)."""
    series: list[SeriesInfo] = []
    if isinstance(query_json, dict) and isinstance(query_json.get("series"), list):
        for node in query_json["series"]:
            if not isinstance(node, dict):
                continue
            if node.get("kind") == "EventsNode" and node.get("event"):
                name = node.get("name") if isinstance(node.get("name"), str) else None
                series.append(SeriesInfo(kind="events", name=name or node["event"]))
            elif node.get("kind") == "ActionsNode" and node.get("id") is not None:
                name = node.get("name") if isinstance(node.get("name"), str) else None
                series.append(SeriesInfo(kind="actions", name=name or f"action:{node['id']}", action_id=node.get("id")))
    elif isinstance(legacy_filters, dict):
        for ev in legacy_filters.get("events") or []:
            if isinstance(ev, dict) and ev.get("name"):
                series.append(SeriesInfo(kind="events", name=ev["name"]))
        for act in legacy_filters.get("actions") or []:
            if isinstance(act, dict) and act.get("id") is not None:
                series.append(
                    SeriesInfo(kind="actions", name=act.get("name") or f"action:{act['id']}", action_id=act.get("id"))
                )
    return series


def extract_date_from(query_json: dict[str, Any] | None, legacy_filters: dict[str, Any] | None) -> str | None:
    """The query's dateRange.date_from across new-query and legacy-filter insight formats."""
    if isinstance(query_json, dict):
        date_range = query_json.get("dateRange")
        if isinstance(date_range, dict) and isinstance(date_range.get("date_from"), str):
            return date_range["date_from"]
    if isinstance(legacy_filters, dict) and isinstance(legacy_filters.get("date_from"), str):
        return legacy_filters["date_from"]
    return None


# ---------------------------------------------------------------------------
# Rename suggestions (mechanical only)
# ---------------------------------------------------------------------------


def suggest_renamed_name(
    old_name: str, verdict: Verdict, *, claim: DateRangeClaim | None, date_from: str | None
) -> str | None:
    """A strictly mechanical replacement, or None when any judgment is needed.

    Date-range: swap the stale phrase for the query's actual window ("Pageviews (last 14 days)" →
    "Pageviews (last 30 days)") — only for exact-day window claims; cadence claims ("weekly
    users") and start-anchored/ISO/all-time windows get no suggestion, because rephrasing them is
    taste, not mechanics. A shorthand claim ("7d") keeps the shorthand style ("14d").
    """
    if (
        verdict is Verdict.STALE_DATE_RANGE
        and claim is not None
        and claim.kind == "window"
        and claim.days is not None
        and date_from
    ):
        days = parse_relative_days(date_from)
        if days is None:
            return None
        if re.fullmatch(r"\d+\s?d", claim.matched.strip(), re.I):
            return old_name.replace(claim.matched, claim.matched.replace(str(claim.days), str(days), 1), 1)
        return old_name.replace(claim.matched, f"last {days} days", 1)
    return None


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


@dataclass
class InsightAssessment:
    verdicts: list[Verdict] = field(default_factory=list)
    action: Action = Action.NONE
    suggested_name: str | None = None
    reason: str = ""

    @property
    def confusing(self) -> bool:
        return bool(self.verdicts)


def assess_insight(
    *,
    name: str | None,
    description: str | None,
    query_json: dict[str, Any] | None,
    legacy_filters: dict[str, Any] | None,
    known_events: set[str] | None = None,
) -> InsightAssessment:
    """Score one saved insight for name/description staleness. The rules are conservative:
    unknown shapes score OK rather than guessing, and a suggested rename is only produced for a
    strictly mechanical token swap."""
    assessment = InsightAssessment()

    date_from = extract_date_from(query_json, legacy_filters)
    series = extract_series(query_json, legacy_filters)

    date_verdict = check_date_range(name, description, date_from)
    if date_verdict:
        assessment.verdicts.append(date_verdict)
        claim = extract_date_claim(name) or extract_date_claim(description)
        suggested = name and suggest_renamed_name(name, date_verdict, claim=claim, date_from=date_from)
        claim_text = f"name/description claims '{claim.matched}' ({claim.canonical()})" if claim else "claimed window"
        assessment.reason = f"{claim_text} but the query's date_from is {date_from!r}"
        if suggested and suggested != name:
            assessment.action = Action.RENAME
            assessment.suggested_name = suggested
        else:
            assessment.action = Action.REPORT
        return assessment

    event_verdict = check_series_event(name, description, series, known_events=known_events)
    if event_verdict:
        assessment.verdicts.append(event_verdict)
        tracked = ", ".join(sorted({s.name for s in series})) or "(no series)"
        assessment.reason = f"name/description references an event the query no longer tracks (query tracks: {tracked})"
        assessment.action = Action.REPORT
        return assessment

    count_verdict = check_series_count(name, series)
    if count_verdict:
        assessment.verdicts.append(count_verdict)
        assessment.reason = f"name implies a comparison ('vs') but the query has {len(series)} series"
        assessment.action = Action.REPORT
        return assessment

    return assessment
