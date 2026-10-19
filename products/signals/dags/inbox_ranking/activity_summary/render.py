"""Pure functions that turn one person's recent activity into the input of an activity summary.

Nothing here reads a database. `dag.py` fetches the rows, and this module filters, caps, samples and
renders them, and estimates what a summary update would cost.

Most activity recorded under a person is not theirs: scouts, agents and scheduled jobs act with the
person's identity. Each filter is a named rule in `Drop`, and `build_input` counts what each rule
removed, so a rule that starts dropping everything, or nothing, shows up in the output.
"""

import re
import math
import random
import hashlib
import datetime
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum

import numpy as np

from posthog.dataclasses import frozen

# Bump on any change to the filters, the caps, the sampling or the rendered layout, so partitions stay comparable.
RENDER_VERSION = 2

WINDOW_DAYS = 28
RECENCY_HALF_LIFE_DAYS = 7
CHARS_PER_TOKEN = 4

# Rows read per person before any filter, newest first. They bound query and memory cost for very
# active people; the filters and caps below work on what is left.
MAX_TASKS_PER_PERSON = 200
MAX_MCP_SESSIONS_PER_PERSON = 300
MAX_ACTIVITY_ROWS_PER_PERSON = 1000

# Units one source may keep from a single UTC day, newest first, so one busy afternoon cannot fill a section.
MAX_UNITS_PER_DAY = 3
TASK_LINES = 12
MCP_LINES = 10
ACTIVITY_LINES = 15
# Per-line caps, so one runaway title or intent cannot take the budget. With them a full prompt
# section stays under SECTIONS_MAX_CHARS; the hard stop is the backstop if the caps change.
TASK_LINE_CHARS = 260
TASK_GOAL_CHARS = 180
TASK_TITLE_CHARS = 100
MAX_TAGS = 5
MAX_TAG_CHARS = 30
MCP_LINE_CHARS = 240
MCP_STEP_CHARS = 110
ACTIVITY_LINE_CHARS = 120
ACTIVITY_NAME_CHARS = 70
SECTIONS_MAX_CHARS = 8000

# Generated intents are a sentence or two. The cap bounds the regex work on a client-supplied value.
MAX_INTENT_CHARS = 1000
# Masking and whitespace folding shorten a text, so the patterns read this many times its cap.
RAW_TEXT_FACTOR = 4
# Task summaries run to a few hundred characters; the cap bounds the regex work on a long one.
MAX_SUMMARY_CHARS = 2000
# The same intent text more often than this on one day, for one person, is a scheduled job.
REPEATED_INTENT_DAILY_LIMIT = 5
# A session needs this many calls that do real work, after plumbing and upkeep, to say what the person tried.
MIN_WORK_CALLS = 2
# A task title with no summary needs this many words to say anything ("root cause" does not).
MIN_BARE_TITLE_WORDS = 8

STEP_SEPARATOR = " → "
TASKS_HEADER = "Tasks the person gave to PostHog AI or the Slack agent ([tags] goal):"
MCP_HEADER = "Sessions of the person's own coding agent over MCP (first step → last step):"
ACTIVITY_HEADER = "Things the person created or changed in PostHog:"

# Tools an agent calls to find its way around, not to do the work: tool discovery, schema reads,
# docs and knowledge lookups, and project lookup or switching. Their intents restate the task.
PLUMBING_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "business-knowledge-document-window-retrieve",
        "business-knowledge-documents-search",
        "business-knowledge-repositories-search",
        "docs-search",
        "generate-app-url",
        "metric-describe",
        "metric-list",
        "organization-details-get",
        "project-get",
        "projects-get",
        "read-data-schema",
        "switch-organization",
        "switch-project",
    }
)
# Agents keep their own notes in skills and request approval reviews on every PR. Heavy agent users
# make hundreds of these calls, and they say nothing about what the person works on.
UPKEEP_TOOL_PREFIXES: tuple[str, ...] = ("skill-", "stamphog-")

# Helper tasks that a task spawns for itself, such as repository selection, carry the parent's origin.
SANDBOX_PROMPT_TITLE = re.compile(r"^\[sandbox_prompt:")
# Titles a button or a workflow writes, with only an id changing. Each collapses to one line with a count.
TEMPLATED_TASK_TITLES: tuple[re.Pattern[str], ...] = (re.compile(r"^Fix failing CI checks in PR #\d+$"),)
_TEMPLATE_ID = re.compile(r"#\d+")
_SUMMARY_LABEL = re.compile(r"^(?:Goal|Asked|Question)\s*:\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Scopes agents write in bulk, such as tags applied to every report they touch.
NOISY_ACTIVITY_SCOPES: frozenset[str] = frozenset({"TaggedItem", "Tag"})
# A scout run writes its changes with this client tag, which the caller cannot set.
SCOUT_CLIENT_PREFIX = "scout:"
# Names that a scheduled job stamps with a date, such as a notebook regenerated every day.
_AUTO_NAME = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|model report", re.IGNORECASE)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#]\S*")
# Whole links, dropped from task summaries: a URL carries no topic the summary text does not already name.
_URL = re.compile(r"<?https?://\S+>?")
# Long runs of word characters: a run that mixes letters and digits is an API key, session token,
# hash or UUID. The digit and letter checks run in `_mask_token`, because lookaheads in the pattern
# rescan the run at every word boundary inside it and take quadratic time on a long input.
_WORD_RUN = re.compile(r"[\w-]{24,}")
_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[A-Za-z]")
_WHITESPACE = re.compile(r"\s+")


class Drop(StrEnum):
    """Why a unit or call did not reach the prompt."""

    PLUMBING_TOOL = "plumbing_tool"
    UPKEEP_TOOL = "upkeep_tool"
    REPEATED_JOB = "repeated_job"
    THIN_SESSION = "thin_session"
    SANDBOX_PROMPT_TASK = "sandbox_prompt_task"
    BARE_TITLE = "bare_title"
    NOISY_SCOPE = "noisy_scope"
    SCOUT_CLIENT = "scout_client"
    AUTO_NAMED_OBJECT = "auto_named_object"
    UNNAMED_OBJECT = "unnamed_object"
    DUPLICATE = "duplicate"
    BURST_CAP = "burst_cap"
    SAMPLE_CAP = "sample_cap"
    SECTIONS_BUDGET = "sections_budget"


@frozen
class McpCall:
    at: datetime.datetime
    tool: str
    intent: str


@frozen
class McpSession:
    calls: tuple[McpCall, ...]


@frozen
class TaskItem:
    """A task the person started, with its latest run's summary and tags."""

    at: datetime.datetime
    title: str
    summary: str | None
    tags: tuple[str, ...]


@frozen
class ActivityItem:
    """One activity log row the person made."""

    at: datetime.datetime
    scope: str
    activity: str
    name: str | None
    client: str | None


@frozen
class Unit:
    """One rendered line, dated by its latest activity."""

    at: datetime.datetime
    text: str


@frozen
class RenderedInput:
    text: str
    n_tasks: int
    n_mcp_sessions: int
    n_activity_lines: int
    task_chars: int
    mcp_chars: int
    activity_chars: int
    input_chars: int
    input_tokens_estimate: int
    drops: dict[str, int]


def _mask_token(match: re.Match[str]) -> str:
    run = match.group()
    return "<token>" if _DIGIT.search(run) and _LETTER.search(run) else run


def bounded_raw(text: str, max_chars: int) -> str:
    """At most `max_chars` of the text, without a word that the cut splits.

    A split secret is too short for the masking patterns to match, so the partial word goes too."""
    if len(text) <= max_chars:
        return text
    end = max_chars
    if not text[end].isspace():
        while end > 0 and not text[end - 1].isspace():
            end -= 1
    return text[:end]


def clean_text(text: str, max_chars: int) -> str:
    """Strip emails, URL query strings and token-like strings, fold the text onto one line, and cut
    it to `max_chars`.

    The cut comes after the masking, so it cannot leave part of a secret unmasked. The patterns read
    a bounded prefix, because event properties are client-supplied and have no length limit."""
    text = bounded_raw(text, max_chars * RAW_TEXT_FACTOR)
    text = _EMAIL.sub("<email>", text)
    text = _URL_QUERY.sub(r"\1", text)
    text = _WORD_RUN.sub(_mask_token, text)
    return _WHITESPACE.sub(" ", text).strip()[:max_chars].strip()


def cap_line(text: str, max_chars: int) -> str:
    """Cut at a word boundary and mark the cut."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


def _day(at: datetime.datetime) -> datetime.date:
    return at.astimezone(datetime.UTC).date()


def job_intents(sessions: Iterable[McpSession]) -> frozenset[tuple[datetime.date, str]]:
    """The (UTC day, intent) pairs that one person sent more than `REPEATED_INTENT_DAILY_LIMIT` times.

    Pass every session of the person, across projects, because a job does not stop being a job when
    it switches project."""
    counts = Counter((_day(call.at), call.intent.strip()) for session in sessions for call in session.calls)
    return frozenset(key for key, count in counts.items() if count > REPEATED_INTENT_DAILY_LIMIT)


def collapse_repeats(intents: Sequence[str]) -> list[str]:
    return [intent for index, intent in enumerate(intents) if index == 0 or intent != intents[index - 1]]


def _call_drop(call: McpCall, jobs: frozenset[tuple[datetime.date, str]]) -> Drop | None:
    if call.tool in PLUMBING_TOOL_NAMES:
        return Drop.PLUMBING_TOOL
    if call.tool.startswith(UPKEEP_TOOL_PREFIXES):
        return Drop.UPKEEP_TOOL
    if (_day(call.at), call.intent.strip()) in jobs:
        return Drop.REPEATED_JOB
    return None


def mcp_unit(session: McpSession, jobs: frozenset[tuple[datetime.date, str]], drops: Counter[str]) -> Unit | None:
    """The session as `first step → last step`, or None when too little real work is left."""
    calls = sorted(session.calls, key=lambda call: call.at)
    work: list[str] = []
    for call in calls:
        if (reason := _call_drop(call, jobs)) is not None:
            drops[reason] += 1
            continue
        if intent := clean_text(call.intent, MAX_INTENT_CHARS):
            work.append(intent)
    if len(work) < MIN_WORK_CALLS:
        drops[Drop.THIN_SESSION] += 1
        return None
    steps = collapse_repeats(work)
    path = cap_line(steps[0], MCP_STEP_CHARS)
    if len(steps) > 1:
        path += STEP_SEPARATOR + cap_line(steps[-1], MCP_STEP_CHARS)
    line = f"- {_day(calls[-1].at).isoformat()} ({len(calls)} calls) {path}"
    return Unit(at=calls[-1].at, text=cap_line(line, MCP_LINE_CHARS))


def summary_goal(summary: str) -> str:
    """The opening sentences of a task summary, which state what was asked, without the label."""
    text = _SUMMARY_LABEL.sub("", clean_text(_URL.sub("", bounded_raw(summary, MAX_SUMMARY_CHARS)), MAX_SUMMARY_CHARS))
    goal = ""
    for sentence in _SENTENCE_END.split(text):
        if goal and len(goal) + len(sentence) + 1 > TASK_GOAL_CHARS:
            break
        goal = f"{goal} {sentence}".strip()
    return cap_line(goal, TASK_GOAL_CHARS)


def _templated_label(title: str) -> str | None:
    for pattern in TEMPLATED_TASK_TITLES:
        if pattern.match(title):
            return _TEMPLATE_ID.sub("#N", title)
    return None


def task_units(tasks: Iterable[TaskItem], drops: Counter[str]) -> list[Unit]:
    """One line per task, with templated titles collapsed to one line per template."""
    units: list[Unit] = []
    templated: dict[str, list[datetime.datetime]] = {}
    for task in tasks:
        title = task.title.strip()
        if SANDBOX_PROMPT_TITLE.match(title):
            drops[Drop.SANDBOX_PROMPT_TASK] += 1
            continue
        if (label := _templated_label(title)) is not None:
            templated.setdefault(label, []).append(task.at)
            continue
        day = _day(task.at).isoformat()
        if task.summary:
            tags = [cap_line(clean_text(tag, MAX_TAG_CHARS * 2), MAX_TAG_CHARS) for tag in task.tags[:MAX_TAGS]]
            tag_text = f"[{', '.join(tag for tag in tags if tag)}] " if any(tags) else ""
            line = f"- {day} {tag_text}{summary_goal(task.summary)}"
        elif len(title.split()) >= MIN_BARE_TITLE_WORDS:
            line = f"- {day} {cap_line(clean_text(title, TASK_TITLE_CHARS * 2), TASK_TITLE_CHARS)}"
        else:
            drops[Drop.BARE_TITLE] += 1
            continue
        units.append(Unit(at=task.at, text=cap_line(line, TASK_LINE_CHARS)))
    for label, times in templated.items():
        latest = max(times)
        units.append(
            Unit(at=latest, text=cap_line(f"- {_day(latest).isoformat()} {label} (x{len(times)})", TASK_LINE_CHARS))
        )
    return units


def activity_units(items: Iterable[ActivityItem], drops: Counter[str]) -> list[Unit]:
    """Changes collapsed to one line per object, creates first, then the most changed, then the newest.

    Lines are already collapsed per object, so they skip the per-day burst cap: a busy day of
    changes to different objects lands on one date and the cap would keep only a few of them."""
    collapsed: dict[tuple[str, str, str], list[datetime.datetime]] = {}
    for item in items:
        name = (item.name or "").strip()
        if item.scope in NOISY_ACTIVITY_SCOPES:
            drops[Drop.NOISY_SCOPE] += 1
        elif (item.client or "").startswith(SCOUT_CLIENT_PREFIX):
            drops[Drop.SCOUT_CLIENT] += 1
        elif not name:
            drops[Drop.UNNAMED_OBJECT] += 1
        elif _AUTO_NAME.search(name):
            drops[Drop.AUTO_NAMED_OBJECT] += 1
        else:
            collapsed.setdefault((item.scope, item.activity, name), []).append(item.at)
    ranked = sorted(
        collapsed.items(),
        key=lambda entry: (entry[0][1] != "created", -len(entry[1]), -max(entry[1]).timestamp()),
    )
    if len(ranked) > ACTIVITY_LINES:
        drops[Drop.SAMPLE_CAP] += len(ranked) - ACTIVITY_LINES
    units: list[Unit] = []
    for (scope, activity, name), times in ranked[:ACTIVITY_LINES]:
        latest = max(times)
        count = f" (x{len(times)})" if len(times) > 1 else ""
        name_text = cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)
        line = f'- {_day(latest).isoformat()} {activity} {scope} "{name_text}"{count}'
        units.append(Unit(at=latest, text=cap_line(line, ACTIVITY_LINE_CHARS)))
    return sorted(units, key=lambda unit: (unit.at, unit.text))


def dedupe_latest(units: Iterable[Unit], drops: Counter[str]) -> list[Unit]:
    """One unit per distinct text, the latest one, in chronological order."""
    latest: dict[str, Unit] = {}
    for unit in units:
        if unit.text in latest:
            drops[Drop.DUPLICATE] += 1
        if unit.text not in latest or unit.at > latest[unit.text].at:
            latest[unit.text] = unit
    return sorted(latest.values(), key=lambda unit: (unit.at, unit.text))


def burst_cap(units: Sequence[Unit], drops: Counter[str]) -> list[Unit]:
    """At most `MAX_UNITS_PER_DAY` units per UTC day, newest first, in chronological order."""
    kept: list[Unit] = []
    per_day: Counter[datetime.date] = Counter()
    for unit in sorted(units, key=lambda unit: (unit.at, unit.text), reverse=True):
        if per_day[_day(unit.at)] >= MAX_UNITS_PER_DAY:
            drops[Drop.BURST_CAP] += 1
            continue
        per_day[_day(unit.at)] += 1
        kept.append(unit)
    return sorted(kept, key=lambda unit: (unit.at, unit.text))


def sampling_seed(partition_key: str, team_id: int, user_id: int) -> int:
    # Not hash(): Python salts it per process, and a re-run must pick the same units.
    digest = hashlib.sha256(f"{partition_key}:{team_id}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def sample_units(units: Sequence[Unit], *, limit: int, as_of: datetime.datetime, seed: int) -> list[Unit]:
    """Up to `limit` units without replacement, weighted towards recent ones, in chronological order.

    Weighted reservoir keys (Efraimidis and Spirakis): each unit draws `u ** (1 / weight)` and the
    largest keys win, so one busy afternoon cannot fill every slot."""
    if len(units) <= limit:
        return sorted(units, key=lambda unit: (unit.at, unit.text))
    rng = random.Random(seed)
    keyed: list[tuple[float, Unit]] = []
    for unit in sorted(units, key=lambda unit: (unit.at, unit.text)):
        age_days = max((as_of - unit.at).total_seconds(), 0.0) / 86400
        weight = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        keyed.append((rng.random() ** (1 / weight), unit))
    chosen = sorted(keyed, key=lambda pair: pair[0], reverse=True)[:limit]
    return sorted((unit for _, unit in chosen), key=lambda unit: (unit.at, unit.text))


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def _section(header: str, units: Sequence[Unit]) -> str:
    return "\n".join([header, *(unit.text for unit in units)]) if units else ""


def _sections_chars(sections: Sequence[tuple[str, list[Unit]]]) -> int:
    return sum(len(_section(header, units)) + 2 for header, units in sections)


def enforce_budget(sections: list[tuple[str, list[Unit]]], drops: Counter[str]) -> None:
    """Drop the oldest unit across sections until the rendered sections fit `SECTIONS_MAX_CHARS`."""
    while _sections_chars(sections) > SECTIONS_MAX_CHARS:
        oldest = min((units[0].at, index) for index, (_, units) in enumerate(sections) if units)
        sections[oldest[1]][1].pop(0)
        drops[Drop.SECTIONS_BUDGET] += 1


def build_input(
    sessions: Iterable[McpSession],
    tasks: Iterable[TaskItem],
    activity: Iterable[ActivityItem],
    *,
    jobs: frozenset[tuple[datetime.date, str]],
    as_of: datetime.datetime,
    seed: int,
) -> RenderedInput | None:
    """The rendered input of one (project, person) pair, or None when nothing survives the filters.

    Order: the named filters, then the burst cap, then the recency-weighted sample, then the hard
    budget, so the sample is drawn from clean units only."""
    drops: Counter[str] = Counter()
    task_pool = burst_cap(dedupe_latest(task_units(tasks, drops), drops), drops)
    mcp_pool = burst_cap(
        dedupe_latest((unit for session in sessions if (unit := mcp_unit(session, jobs, drops)) is not None), drops),
        drops,
    )
    activity_lines = activity_units(activity, drops)
    if not task_pool and not mcp_pool and not activity_lines:
        return None
    # Separate seeds per source, so new activity in one source does not reshuffle another.
    chosen_tasks = sample_units(task_pool, limit=TASK_LINES, as_of=as_of, seed=seed)
    chosen_mcp = sample_units(mcp_pool, limit=MCP_LINES, as_of=as_of, seed=seed + 1)
    drops[Drop.SAMPLE_CAP] += len(task_pool) - len(chosen_tasks) + len(mcp_pool) - len(chosen_mcp)
    sections = [(TASKS_HEADER, chosen_tasks), (MCP_HEADER, chosen_mcp), (ACTIVITY_HEADER, activity_lines)]
    enforce_budget(sections, drops)
    rendered = [_section(header, units) for header, units in sections]
    text = "\n\n".join(part for part in rendered if part)
    return RenderedInput(
        text=text,
        n_tasks=len(sections[0][1]),
        n_mcp_sessions=len(sections[1][1]),
        n_activity_lines=len(sections[2][1]),
        task_chars=len(rendered[0]),
        mcp_chars=len(rendered[1]),
        activity_chars=len(rendered[2]),
        input_chars=len(text),
        input_tokens_estimate=estimate_tokens(len(text)),
        drops={str(reason): count for reason, count in sorted(drops.items()) if count},
    )


# `- 2026-01-31 (12 calls) ` before the steps and ` → ` between them, for the projection's length estimate.
MCP_LINE_PREFIX_CHARS = 24 + len(STEP_SEPARATOR)


@frozen
class PairActivity:
    """MCP counts and lengths for one (project, person) pair, as the projection SQL computes them.

    The projection covers only the MCP section: tasks and activity are capped per person, so their
    share of a prompt has a known upper bound and goes in as a fixed overhead."""

    mcp_sessions: int
    mcp_avg_line_chars: float

    @property
    def units(self) -> int:
        return self.mcp_sessions


def estimated_input_chars(activity: PairActivity) -> int:
    """The length the MCP section would get: a sample of average-length lines under its header."""
    if activity.mcp_sessions <= 0:
        return 0
    sampled = min(activity.mcp_sessions, MCP_LINES)
    return round(len(MCP_HEADER) + sampled * (min(activity.mcp_avg_line_chars, MCP_LINE_CHARS) + 1))


def capped_sections_tokens() -> int:
    """The most tokens the task and activity sections can take under their caps."""
    tasks = len(TASKS_HEADER) + TASK_LINES * (TASK_LINE_CHARS + 1)
    activity = len(ACTIVITY_HEADER) + ACTIVITY_LINES * (ACTIVITY_LINE_CHARS + 1)
    return estimate_tokens(tasks + activity)


def calibration_ratio[K](actual_chars: Mapping[K, int], estimated_chars: Mapping[K, int]) -> float:
    """How far the SQL estimate is from the real rendered length, over the pairs both sides have.

    1.0 when no pair matches, so a missing inputs partition leaves the estimate as it is."""
    keys = [key for key in actual_chars if estimated_chars.get(key, 0) > 0]
    estimated = sum(estimated_chars[key] for key in keys)
    if not estimated:
        return 1.0
    return sum(actual_chars[key] for key in keys) / estimated


def updates_per_window(units: int, *, min_units: int, min_days: int) -> int:
    """Updates a pair earns in the window: one per `min_units` new units, at most one per `min_days`."""
    return min(units // min_units, WINDOW_DAYS // min_days)


MIN_UNITS_OPTIONS = (3, 5, 10)
MIN_DAYS_OPTIONS = (7, 14)
DAYS_PER_MONTH = 30


@frozen
class ProjectionPrices:
    prompt_overhead_tokens: int
    output_tokens_per_update: int
    input_price_per_million_tokens: float | None
    output_price_per_million_tokens: float | None


def _percentile(values: Sequence[int], q: float) -> int | None:
    return int(np.percentile(values, q)) if values else None


def projection_rows(activities: Sequence[PairActivity], *, ratio: float, prices: ProjectionPrices) -> list[dict]:
    """One row per (`MIN_UNITS`, `MIN_DAYS`) option: eligible pairs, input token percentiles, and the
    monthly volume and cost. Counts only: no pair is named."""
    tokens = [estimate_tokens(round(estimated_input_chars(activity) * ratio)) for activity in activities]
    rows: list[dict] = []
    for min_units in MIN_UNITS_OPTIONS:
        eligible = [index for index, activity in enumerate(activities) if activity.units >= min_units]
        eligible_tokens = [tokens[index] for index in eligible]
        for min_days in MIN_DAYS_OPTIONS:
            monthly_updates = [
                updates_per_window(activities[index].units, min_units=min_units, min_days=min_days)
                * DAYS_PER_MONTH
                / WINDOW_DAYS
                for index in eligible
            ]
            updates = sum(monthly_updates)
            input_tokens = sum(
                count * (tokens[index] + prices.prompt_overhead_tokens)
                for count, index in zip(monthly_updates, eligible, strict=True)
            )
            output_tokens = updates * prices.output_tokens_per_update
            cost = None
            if prices.input_price_per_million_tokens is not None and prices.output_price_per_million_tokens is not None:
                cost = (
                    input_tokens * prices.input_price_per_million_tokens
                    + output_tokens * prices.output_price_per_million_tokens
                ) / 1_000_000
            rows.append(
                {
                    "min_units": min_units,
                    "min_days": min_days,
                    "eligible_pairs": len(eligible),
                    "input_tokens_p50": _percentile(eligible_tokens, 50),
                    "input_tokens_p90": _percentile(eligible_tokens, 90),
                    "input_tokens_p99": _percentile(eligible_tokens, 99),
                    "updates_per_month": updates,
                    "input_tokens_per_month": input_tokens,
                    "output_tokens_per_month": output_tokens,
                    "projected_monthly_cost_usd": cost,
                    "calibration_ratio": ratio,
                }
            )
    return rows
