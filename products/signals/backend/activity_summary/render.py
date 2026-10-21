"""Pure functions that turn one person's recent activity in one project into the input of an activity summary.

Nothing here reads a database. `inputs.py` fetches the rows, and this module filters, caps, samples
and renders them.

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
from collections.abc import Iterable, Sequence
from enum import StrEnum
from urllib.parse import urlsplit

from posthog.dataclasses import frozen

# Bump on any change to the filters, the caps, the sampling or the rendered layout, so summaries stay comparable.
RENDER_VERSION = 3

WINDOW_DAYS = 28
RECENCY_HALF_LIFE_DAYS = 7
CHARS_PER_TOKEN = 4

# Rows read per person before any filter, newest first. They bound query and memory cost for very
# active people; the filters and caps below work on what is left.
MAX_TASKS_PER_PERSON = 200
MAX_ACTIVITY_ROWS_PER_PERSON = 1000

# Units one source may keep from a single UTC day, newest first, so one busy afternoon cannot fill a section.
MAX_UNITS_PER_DAY = 3
TASK_LINES = 12
ACTIVITY_LINES = 15
# Per-line caps, so one runaway title or intent cannot take the budget. With them a full prompt
# section stays under SECTIONS_MAX_CHARS; the hard stop is the backstop if the caps change.
TASK_LINE_CHARS = 260
TASK_GOAL_CHARS = 180
TASK_TITLE_CHARS = 100
MAX_TAGS = 5
MAX_TAG_CHARS = 30
ACTIVITY_LINE_CHARS = 220
ACTIVITY_NAME_CHARS = 70
ACTIVITY_INTENT_CHARS = 100
SECTIONS_MAX_CHARS = 8000

# Masking and whitespace folding shorten a text, so the patterns read this many times its cap.
RAW_TEXT_FACTOR = 4
# Task summaries run to a few hundred characters; the cap bounds the regex work on a long one.
MAX_SUMMARY_CHARS = 2000
# A task title with no summary needs this many words to say anything ("root cause" does not).
MIN_BARE_TITLE_WORDS = 8

TASKS_HEADER = "Tasks the person gave to PostHog AI or the Slack agent ([tags] goal):"
ACTIVITY_HEADER = "Things the person created or changed in PostHog (agent: why their coding agent did it):"

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
_URL = re.compile(r"<?https?://[^\s<>]+>?")
# Long runs of word characters: a run that mixes letters and digits is an API key, session token,
# hash or UUID. The digit and letter checks run in `_mask_token`, because lookaheads in the pattern
# rescan the run at every word boundary inside it and take quadratic time on a long input.
_WORD_RUN = re.compile(r"[\w-]{24,}")
_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[A-Za-z]")
_WHITESPACE = re.compile(r"\s+")


class Drop(StrEnum):
    """Why a unit did not reach the prompt."""

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
class TaskItem:
    """A task the person started, with its latest run's summary and tags."""

    at: datetime.datetime
    title: str
    summary: str | None
    tags: tuple[str, ...]


@frozen
class ActivityItem:
    """One activity log row the person made, with the intent their agent sent, if any."""

    at: datetime.datetime
    scope: str
    activity: str
    name: str | None
    client: str | None
    intent: str | None = None


@frozen
class Unit:
    """One rendered line, dated by its latest activity."""

    at: datetime.datetime
    text: str


@frozen
class RenderedInput:
    text: str
    n_tasks: int
    n_activity_lines: int
    task_chars: int
    activity_chars: int
    input_chars: int
    input_tokens_estimate: int
    drops: dict[str, int]

    @property
    def units(self) -> int:
        return self.n_tasks + self.n_activity_lines


def _mask_token(match: re.Match[str]) -> str:
    run = match.group()
    return "<token>" if _DIGIT.search(run) and _LETTER.search(run) else run


def _url_host(match: re.Match[str]) -> str:
    """Only the host of a URL: a secret can sit in a path, a query string or a fragment."""
    try:
        host = urlsplit(match.group().strip("<>")).hostname
    except ValueError:
        host = None
    return f"[link {host}]" if host else "[link]"


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
    """Replace emails, URLs and token-like strings, fold the text onto one line, and cut it to `max_chars`.

    A URL keeps only its host. The cut comes after the masking, so it cannot leave part of a secret
    unmasked. The patterns read a bounded prefix, because the free text has no length limit."""
    text = bounded_raw(text, max_chars * RAW_TEXT_FACTOR)
    text = _URL.sub(_url_host, text)
    text = _EMAIL.sub("<email>", text)
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


def summary_goal(summary: str) -> str:
    """The opening sentences of a task summary, which state what was asked, without the label."""
    text = _SUMMARY_LABEL.sub("", clean_text(bounded_raw(summary, MAX_SUMMARY_CHARS), MAX_SUMMARY_CHARS))
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

    A line carries the newest agent intent of its rows. Lines are already collapsed per object, so
    they skip the per-day burst cap: a busy day of changes to different objects lands on one date
    and the cap would keep only a few of them."""
    collapsed: dict[tuple[str, str, str], list[ActivityItem]] = {}
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
            collapsed.setdefault((item.scope, item.activity, name), []).append(item)
    ranked = sorted(
        collapsed.items(),
        key=lambda entry: (
            entry[0][1] != "created",
            -len(entry[1]),
            -max(row.at for row in entry[1]).timestamp(),
        ),
    )
    if len(ranked) > ACTIVITY_LINES:
        drops[Drop.SAMPLE_CAP] += len(ranked) - ACTIVITY_LINES
    units: list[Unit] = []
    for (scope, activity, name), rows in ranked[:ACTIVITY_LINES]:
        latest = max(row.at for row in rows)
        count = f" (x{len(rows)})" if len(rows) > 1 else ""
        name_text = cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)
        line = f'- {_day(latest).isoformat()} {activity} {scope} "{name_text}"{count}'
        intents = [row for row in rows if row.intent and row.intent.strip()]
        if intents:
            intent = max(intents, key=lambda row: row.at).intent or ""
            intent_text = cap_line(clean_text(intent, ACTIVITY_INTENT_CHARS * 2), ACTIVITY_INTENT_CHARS)
            if intent_text:
                line += f" (agent: {intent_text})"
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


def sampling_seed(seed_key: str, team_id: int, user_id: int) -> int:
    # Not hash(): Python salts it per process, and a re-run must pick the same units.
    digest = hashlib.sha256(f"{seed_key}:{team_id}:{user_id}".encode()).digest()
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
    tasks: Iterable[TaskItem],
    activity: Iterable[ActivityItem],
    *,
    as_of: datetime.datetime,
    seed: int,
) -> RenderedInput | None:
    """The rendered input of one (project, person) pair, or None when nothing survives the filters.

    Order: the named filters, then the burst cap, then the recency-weighted sample, then the hard
    budget, so the sample is drawn from clean units only."""
    drops: Counter[str] = Counter()
    task_pool = burst_cap(dedupe_latest(task_units(tasks, drops), drops), drops)
    activity_lines = activity_units(activity, drops)
    if not task_pool and not activity_lines:
        return None
    chosen_tasks = sample_units(task_pool, limit=TASK_LINES, as_of=as_of, seed=seed)
    drops[Drop.SAMPLE_CAP] += len(task_pool) - len(chosen_tasks)
    sections = [(TASKS_HEADER, chosen_tasks), (ACTIVITY_HEADER, activity_lines)]
    enforce_budget(sections, drops)
    rendered = [_section(header, units) for header, units in sections]
    text = "\n\n".join(part for part in rendered if part)
    return RenderedInput(
        text=text,
        n_tasks=len(sections[0][1]),
        n_activity_lines=len(sections[1][1]),
        task_chars=len(rendered[0]),
        activity_chars=len(rendered[1]),
        input_chars=len(text),
        input_tokens_estimate=estimate_tokens(len(text)),
        drops={str(reason): count for reason, count in sorted(drops.items()) if count},
    )
