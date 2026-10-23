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
import dataclasses
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from posthog.dataclasses import frozen

# Bump on any code change to the filters, the default caps, the sampling or the rendered layout, so summaries
# stay comparable. Limits from the flag payload go into `inputs_used` instead.
RENDER_VERSION = 6

WINDOW_DAYS = 28
RECENCY_HALF_LIFE_DAYS = 7
CHARS_PER_TOKEN = 4

# Rows read per person, newest first. They bound query and memory cost for very active people. The
# query applies the noise filters before this limit, so bulk agent writes cannot fill it.
MAX_TASKS_PER_PERSON = 200
MAX_ACTIVITY_ROWS_PER_PERSON = 1000
MAX_VIEW_ROWS_PER_PERSON = 500

# Units one source may keep from a single UTC day, newest first, so one busy afternoon cannot fill a section.
MAX_UNITS_PER_DAY = 3
TASK_LINES = 12
ACTIVITY_LINES = 15
# Activity lines one UTC day may keep while other days have lines to show. A third of the section
# leaves a busy day several lines and the rest of the window most of the slots.
MAX_ACTIVITY_LINES_PER_DAY = 5
VIEW_LINES = 15
# Per-line caps, so one runaway title or intent cannot take the budget. With the default caps a full
# prompt section stays under SECTIONS_MAX_CHARS; the hard stop is the backstop when the caps change.
TASK_LINE_CHARS = 260
TASK_GOAL_CHARS = 180
TASK_TITLE_CHARS = 100
MAX_TAGS = 5
MAX_TAG_CHARS = 30
ACTIVITY_LINE_CHARS = 220
ACTIVITY_NAME_CHARS = 70
ACTIVITY_INTENT_CHARS = 100
VIEW_LINE_CHARS = 160
SECTIONS_MAX_CHARS = 8000
# Hidden reasoning tokens count against the cap too, so a cap near the answer size truncates answers.
MAX_COMPLETION_TOKENS = 4000
# About 1,500 output tokens: one page of markdown. The prompt asks for it, and the normalization cuts a longer profile.
PROFILE_MAX_CHARS = 6000

# Masking and whitespace folding shorten a text, so the patterns read this many times its cap.
RAW_TEXT_FACTOR = 4
# Task summaries run to a few hundred characters; the cap bounds the regex work on a long one.
MAX_SUMMARY_CHARS = 2000
# A task title with no summary needs this many words to say anything ("root cause" does not).
MIN_BARE_TITLE_WORDS = 8

TASKS_HEADER = "Tasks the person gave to PostHog AI or the Slack agent ([tags] goal):"
ACTIVITY_HEADER = "Things the person created or changed in PostHog (agent: why their coding agent did it):"
VIEWS_HEADER = "Things the person opened in PostHog, by type (days: distinct days in the window; not theirs: someone else made it):"

# Helper tasks that a task spawns for itself, such as repository selection, carry the parent's origin.
SANDBOX_PROMPT_TITLE_PREFIX = "[sandbox_prompt:"
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

# A view log row of this type records a page, and its ref is the frontend scene id.
SCENE_VIEW_TYPE = "scene"
# The product of each scene id prefix. A prefix matches its plural and any longer scene id of the
# same product, such as "ErrorTrackingIssue". Other scenes, such as settings, the home page or a new
# tab, say nothing about the work.
_SCENE_PRODUCTS: tuple[tuple[str, str], ...] = (
    ("Insight|SavedInsight|ProductAnalytics", "Product analytics"),
    ("Dashboard", "Dashboards"),
    ("WebAnalytics", "Web analytics"),
    ("Replay|SessionRecording|SessionSummaries", "Session replay"),
    ("Heatmap", "Heatmaps"),
    ("ErrorTracking", "Error tracking"),
    ("Experiment", "Experiments"),
    ("FeatureFlag", "Feature flags"),
    ("EarlyAccessFeature", "Early access features"),
    ("Survey", "Surveys"),
    ("ProductTour", "Product tours"),
    ("Notebook", "Notebooks"),
    ("Cohort", "Cohorts"),
    ("Person|Group", "Persons and groups"),
    ("Action|EventDefinition|PropertyDefinition|DataManagement", "Data management"),
    ("SQLEditor|DataWarehouse|Sources|Models", "Data warehouse"),
    ("Pipeline|Destination|Transformation|HogFunction|BatchExport", "Data pipelines"),
    ("Workflow|Broadcast", "Workflows"),
    ("AIObservability", "AI observability"),
    ("MCPAnalytics", "MCP analytics"),
    ("Logs", "Logs"),
    ("Tracing", "Tracing"),
    ("Endpoint", "Endpoints"),
    ("RevenueAnalytics", "Revenue analytics"),
    ("CustomerAnalytics", "Customer analytics"),
    ("Inbox", "Inbox"),
    ("Canvas", "Canvases"),
)
_SCENE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"^(?:{prefixes})s?(?:[A-Z]|$)"), product) for prefixes, product in _SCENE_PRODUCTS
)


def _limit(default: int, *, max_value: int) -> Any:
    return dataclasses.field(default=default, metadata={"max_value": max_value})


@frozen
class RenderLimits:
    """The limits that shape one summary. The `activity-summary` flag payload can override each one.

    `max_value` clamps a payload value, so a typo cannot make one update slow or expensive."""

    window_days: int = _limit(WINDOW_DAYS, max_value=90)
    task_lines: int = _limit(TASK_LINES, max_value=50)
    activity_lines: int = _limit(ACTIVITY_LINES, max_value=50)
    max_activity_lines_per_day: int = _limit(MAX_ACTIVITY_LINES_PER_DAY, max_value=50)
    view_lines: int = _limit(VIEW_LINES, max_value=50)
    view_line_chars: int = _limit(VIEW_LINE_CHARS, max_value=1000)
    max_units_per_day: int = _limit(MAX_UNITS_PER_DAY, max_value=20)
    sections_max_chars: int = _limit(SECTIONS_MAX_CHARS, max_value=32000)
    task_line_chars: int = _limit(TASK_LINE_CHARS, max_value=1000)
    task_goal_chars: int = _limit(TASK_GOAL_CHARS, max_value=800)
    activity_line_chars: int = _limit(ACTIVITY_LINE_CHARS, max_value=1000)
    activity_intent_chars: int = _limit(ACTIVITY_INTENT_CHARS, max_value=500)
    profile_max_chars: int = _limit(PROFILE_MAX_CHARS, max_value=20000)
    max_completion_tokens: int = _limit(MAX_COMPLETION_TOKENS, max_value=16000)


DEFAULT_LIMITS = RenderLimits()
MAX_LIMITS = RenderLimits(**{field.name: field.metadata["max_value"] for field in dataclasses.fields(RenderLimits)})


class Drop(StrEnum):
    """Why a unit did not reach the prompt."""

    SANDBOX_PROMPT_TASK = "sandbox_prompt_task"
    BARE_TITLE = "bare_title"
    NOISY_SCOPE = "noisy_scope"
    SCOUT_CLIENT = "scout_client"
    AUTO_NAMED_OBJECT = "auto_named_object"
    UNNAMED_OBJECT = "unnamed_object"
    GENERIC_SCENE = "generic_scene"
    DUPLICATE = "duplicate"
    GROUPED_INTO_PARENT = "grouped_into_parent"
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
    item_id: str | None = None


@frozen
class Parent:
    """An object that holds another, such as the dashboard an insight sits on."""

    scope: str
    item_id: str
    name: str


# Parents of an object in preference order, keyed by the object's (scope, item_id).
ParentLookup = Mapping[tuple[str, str], Sequence[Parent]]


@frozen
class ViewItem:
    """One object or scene the person opened, with the days they opened it.

    `name` is None for a scene, and for an object that has no file system entry."""

    at: datetime.datetime
    type: str
    ref: str
    name: str | None
    days: tuple[datetime.date, ...]
    not_theirs: bool = False


@frozen
class Unit:
    """One rendered line, dated by its latest activity."""

    at: datetime.datetime
    text: str


@frozen
class _ActivityLine:
    """A rendered activity line with the fields that rank it."""

    at: datetime.datetime
    text: str
    created: bool
    rows: int


@frozen
class RenderedInput:
    text: str
    n_tasks: int
    n_activity_lines: int
    n_view_lines: int
    task_chars: int
    activity_chars: int
    view_chars: int
    input_chars: int
    input_tokens_estimate: int
    drops: dict[str, int]
    # Units of each source before its line cap, so a caller can tell when the cap binds.
    task_pool: int
    activity_pool: int

    @property
    def units(self) -> int:
        return self.n_tasks + self.n_activity_lines + self.n_view_lines


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


def summary_goal(summary: str, max_chars: int = TASK_GOAL_CHARS) -> str:
    """The opening sentences of a task summary, which state what was asked, without the label."""
    text = _SUMMARY_LABEL.sub("", clean_text(bounded_raw(summary, MAX_SUMMARY_CHARS), MAX_SUMMARY_CHARS))
    goal = ""
    for sentence in _SENTENCE_END.split(text):
        if goal and len(goal) + len(sentence) + 1 > max_chars:
            break
        goal = f"{goal} {sentence}".strip()
    return cap_line(goal, max_chars)


def _templated_label(title: str) -> str | None:
    for pattern in TEMPLATED_TASK_TITLES:
        if pattern.match(title):
            return _TEMPLATE_ID.sub("#N", title)
    return None


def task_units(tasks: Iterable[TaskItem], drops: Counter[str], limits: RenderLimits = DEFAULT_LIMITS) -> list[Unit]:
    """One line per task, with templated titles collapsed to one line per template."""
    units: list[Unit] = []
    templated: dict[str, list[datetime.datetime]] = {}
    for task in tasks:
        title = task.title.strip()
        if title.startswith(SANDBOX_PROMPT_TITLE_PREFIX):
            drops[Drop.SANDBOX_PROMPT_TASK] += 1
            continue
        if (label := _templated_label(title)) is not None:
            templated.setdefault(label, []).append(task.at)
            continue
        day = _day(task.at).isoformat()
        if task.summary:
            tags = [cap_line(clean_text(tag, MAX_TAG_CHARS * 2), MAX_TAG_CHARS) for tag in task.tags[:MAX_TAGS]]
            tag_text = f"[{', '.join(tag for tag in tags if tag)}] " if any(tags) else ""
            line = f"- {day} {tag_text}{summary_goal(task.summary, limits.task_goal_chars)}"
        elif len(title.split()) >= MIN_BARE_TITLE_WORDS:
            line = f"- {day} {cap_line(clean_text(title, TASK_TITLE_CHARS * 2), TASK_TITLE_CHARS)}"
        else:
            drops[Drop.BARE_TITLE] += 1
            continue
        units.append(Unit(at=task.at, text=cap_line(line, limits.task_line_chars)))
    for label, times in templated.items():
        latest = max(times)
        units.append(
            Unit(
                at=latest,
                text=cap_line(f"- {_day(latest).isoformat()} {label} (x{len(times)})", limits.task_line_chars),
            )
        )
    return units


ObjectKey = tuple[str, str, str]


def _intent_suffix(rows: Iterable[ActivityItem], max_chars: int) -> str:
    intents = [row for row in rows if row.intent and row.intent.strip()]
    if not intents:
        return ""
    intent = max(intents, key=lambda row: row.at).intent or ""
    intent_text = cap_line(clean_text(intent, max_chars * 2), max_chars)
    return f" (agent: {intent_text})" if intent_text else ""


def _display_name(name: str) -> str:
    return cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)


def _quoted_names(names: Sequence[str], max_chars: int) -> str:
    """Quoted names joined by commas, as many as fit in `max_chars`, with "…" for the rest."""
    text = ", ".join(f'"{name}"' for name in names)
    if len(text) <= max_chars:
        return text
    text = ""
    for name in names:
        part = f'"{name}"' if not text else f', "{name}"'
        if len(text) + len(part) + len(", …") > max_chars:
            break
        text += part
    return f"{text}, …" if text else "…"


def _usable_parents(parents: Sequence[Parent]) -> list[Parent]:
    """Parents with a name worth showing: a scheduled job's auto-named object says nothing."""
    usable: list[Parent] = []
    for parent in parents:
        name = parent.name.strip()
        if name and not _AUTO_NAME.search(name) and parent not in usable:
            usable.append(parent)
    return usable


def _object_line(
    scope: str, activity: str, name: str, rows: Sequence[ActivityItem], context: str, limits: RenderLimits
) -> _ActivityLine:
    latest = max(row.at for row in rows)
    count = f" (x{len(rows)})" if len(rows) > 1 else ""
    line = f'- {_day(latest).isoformat()} {activity} {scope} "{_display_name(name)}"{context}{count}'
    return _ActivityLine(
        at=latest,
        text=cap_line(line + _intent_suffix(rows, limits.activity_intent_chars), limits.activity_line_chars),
        created=activity == "created",
        rows=len(rows),
    )


def _group_line(
    parent: Parent,
    own: Sequence[ObjectKey],
    children: Sequence[ObjectKey],
    collapsed: Mapping[ObjectKey, list[ActivityItem]],
    limits: RenderLimits,
) -> _ActivityLine:
    """One line for a parent and the children merged into it, children ranked like lines."""
    rows = [row for key in (*own, *children) for row in collapsed[key]]
    latest = max(row.at for row in rows)
    ranked_children = sorted(
        children,
        key=lambda key: (
            key[1] != "created",
            -len(collapsed[key]),
            -max(row.at for row in collapsed[key]).timestamp(),
            key[2],
        ),
    )
    names = list(dict.fromkeys(_display_name(key[2]) for key in ranked_children))
    counts = Counter(scope for scope, _ in dict.fromkeys((key[0], key[2]) for key in children))
    child_text = ", ".join(f"{count} {scope}{'s' if count != 1 else ''}" for scope, count in sorted(counts.items()))
    parent_text = f'{parent.scope} "{_display_name(parent.name)}"'
    if any(key[1] == "created" for key in own):
        head = f"created {parent_text} with {child_text}: "
    else:
        activities = sorted({key[1] for key in children}, key=lambda activity: (activity != "created", activity))
        head = f"{' and '.join(activities)} {child_text} on {parent_text}: "
    head = f"- {_day(latest).isoformat()} {head}"
    intent = _intent_suffix(rows, limits.activity_intent_chars)
    line = head + _quoted_names(names, limits.activity_line_chars - len(head) - len(intent)) + intent
    return _ActivityLine(
        at=latest,
        text=cap_line(line, limits.activity_line_chars),
        created=any(row.activity == "created" for row in rows),
        rows=len(rows),
    )


def _lines_with_parents(
    collapsed: Mapping[ObjectKey, list[ActivityItem]], parents: ParentLookup, drops: Counter[str], limits: RenderLimits
) -> list[_ActivityLine]:
    """One line per object, with the objects that share a parent merged into one line for the parent.

    The parent's own rows merge into its line. An object whose parent holds no other changed object
    keeps its own line and names the parent."""
    child_parents: dict[ObjectKey, list[Parent]] = {}
    for key, rows in collapsed.items():
        found = [parent for row in rows if row.item_id for parent in parents.get((row.scope, row.item_id), ())]
        if usable := _usable_parents(found):
            child_parents[key] = usable
    by_identity = {(parent.scope, parent.item_id): parent for usable in child_parents.values() for parent in usable}
    own: dict[Parent, list[ObjectKey]] = {}
    for key, rows in collapsed.items():
        identities = dict.fromkeys((row.scope, row.item_id) for row in rows if row.item_id)
        for identity in identities:
            if (parent := by_identity.get(identity)) is not None:
                own.setdefault(parent, []).append(key)
    # Each child picks the parent that holds the most changed objects, so a group forms where the work was.
    weight = Counter(parent for usable in child_parents.values() for parent in usable)
    weight.update({parent: len(keys) for parent, keys in own.items()})
    chosen: dict[Parent, list[ObjectKey]] = {}
    for key, usable in child_parents.items():
        chosen.setdefault(max(usable, key=lambda parent: weight[parent]), []).append(key)

    lines: list[_ActivityLine] = []
    merged: set[ObjectKey] = set()
    for parent, children in chosen.items():
        parent_own = [key for key in own.get(parent, []) if key not in child_parents]
        distinct_children = {(key[0], key[2]) for key in children}
        if len(distinct_children) < 2 and not parent_own:
            continue
        lines.append(_group_line(parent, parent_own, children, collapsed, limits))
        merged.update(parent_own, children)
        drops[Drop.GROUPED_INTO_PARENT] += len(parent_own) + len(children) - 1
    for key, rows in collapsed.items():
        if key in merged:
            continue
        context = ""
        if key in child_parents:
            usable = child_parents[key]
            parent = max(usable, key=lambda parent: weight[parent])
            more = f" (+{len(usable) - 1} more)" if len(usable) > 1 else ""
            context = f' on {parent.scope} "{_display_name(parent.name)}"{more}'
        lines.append(_object_line(*key, rows, context, limits))
    return lines


def _spread_across_days(
    ranked: Sequence[_ActivityLine], drops: Counter[str], limits: RenderLimits
) -> list[_ActivityLine]:
    """The first `limits.activity_lines` lines in rank order, at most `limits.max_activity_lines_per_day` from one UTC day.

    Lines over a day's cap fill the slots that no other day takes, so a single busy day still shows."""
    kept: list[_ActivityLine] = []
    deferred: list[_ActivityLine] = []
    per_day: Counter[datetime.date] = Counter()
    for line in ranked:
        if per_day[_day(line.at)] >= limits.max_activity_lines_per_day:
            deferred.append(line)
        elif len(kept) < limits.activity_lines:
            per_day[_day(line.at)] += 1
            kept.append(line)
        else:
            drops[Drop.SAMPLE_CAP] += 1
    backfill = deferred[: limits.activity_lines - len(kept)]
    if len(deferred) > len(backfill):
        drops[Drop.BURST_CAP] += len(deferred) - len(backfill)
    return kept + backfill


def activity_units(
    items: Iterable[ActivityItem],
    drops: Counter[str],
    parents: ParentLookup | None = None,
    limits: RenderLimits = DEFAULT_LIMITS,
) -> list[Unit]:
    """Changes collapsed to one line per object, or per parent, creates first, then the most changed, then the newest.

    A line carries the newest agent intent of its rows. A day keeps at most `limits.max_activity_lines_per_day`
    lines while other days have lines left, not the `MAX_UNITS_PER_DAY` of tasks: lines are already
    collapsed per object, and a busy day of changes to different objects is more than three things."""
    collapsed: dict[ObjectKey, list[ActivityItem]] = {}
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
    lines = _lines_with_parents(collapsed, parents or {}, drops, limits)
    ranked = sorted(lines, key=lambda line: (not line.created, -line.rows, -line.at.timestamp(), line.text))
    kept = _spread_across_days(ranked, drops, limits)
    return sorted((Unit(at=line.at, text=line.text) for line in kept), key=lambda unit: (unit.at, unit.text))


def scene_product(scene_id: str) -> str | None:
    for pattern, product in _SCENE_PATTERNS:
        if pattern.match(scene_id):
            return product
    return None


def _scope_of(view_type: str) -> str:
    """The activity log scope of a file system type, such as "FeatureFlag" for "feature_flag"."""
    return "".join(word.capitalize() for word in view_type.split("/")[0].split("_"))


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def view_units(
    views: Iterable[ViewItem],
    activity: Iterable[ActivityItem],
    drops: Counter[str],
    limits: RenderLimits = DEFAULT_LIMITS,
) -> list[Unit]:
    """One line per opened object and one per product of the opened scenes, the most opened first.

    An object line also counts the days the person edited it, matched to their activity rows by
    scope and name. These lines skip the per-day burst cap."""
    edit_days: dict[tuple[str, str], set[datetime.date]] = {}
    for item in activity:
        if item.name and not (item.client or "").startswith(SCOUT_CLIENT_PREFIX):
            edit_days.setdefault((item.scope, item.name.strip()), set()).add(_day(item.at))
    ranked: list[tuple[int, datetime.datetime, str]] = []
    scenes: dict[str, tuple[datetime.datetime, set[datetime.date]]] = {}
    for view in views:
        if view.type == SCENE_VIEW_TYPE:
            product = scene_product(view.ref)
            if product is None:
                drops[Drop.GENERIC_SCENE] += 1
                continue
            at, days = scenes.get(product, (view.at, set()))
            scenes[product] = (max(at, view.at), days | set(view.days))
            continue
        name = (view.name or "").strip()
        if not name:
            drops[Drop.UNNAMED_OBJECT] += 1
            continue
        if _AUTO_NAME.search(name):
            drops[Drop.AUTO_NAMED_OBJECT] += 1
            continue
        opened = len(set(view.days))
        name_text = cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)
        facts = [f"opened {_days(opened)}", f"last {_day(view.at).isoformat()}"]
        if edited := len(edit_days.get((_scope_of(view.type), name), ())):
            facts.append(f"edited {_days(edited)}")
        if view.not_theirs:
            facts.append("not theirs")
        label = view.type.split("/")[0].replace("_", " ").capitalize()
        ranked.append((opened, view.at, f'- {label} "{name_text}": {", ".join(facts)}'))
    for product, (at, days) in scenes.items():
        ranked.append((len(days), at, f"- {product} pages: opened {_days(len(days))}, last {_day(at).isoformat()}"))
    ranked.sort(key=lambda entry: (-entry[0], -entry[1].timestamp(), entry[2]))
    if len(ranked) > limits.view_lines:
        drops[Drop.SAMPLE_CAP] += len(ranked) - limits.view_lines
    units = [Unit(at=at, text=cap_line(text, limits.view_line_chars)) for _, at, text in ranked[: limits.view_lines]]
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


def burst_cap(units: Sequence[Unit], drops: Counter[str], max_per_day: int = MAX_UNITS_PER_DAY) -> list[Unit]:
    """At most `max_per_day` units per UTC day, newest first, in chronological order."""
    kept: list[Unit] = []
    per_day: Counter[datetime.date] = Counter()
    for unit in sorted(units, key=lambda unit: (unit.at, unit.text), reverse=True):
        if per_day[_day(unit.at)] >= max_per_day:
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


def enforce_budget(
    sections: list[tuple[str, list[Unit]]], drops: Counter[str], max_chars: int = SECTIONS_MAX_CHARS
) -> None:
    """Drop the oldest unit across sections until the rendered sections fit `max_chars`, or no unit is left."""
    while _sections_chars(sections) > max_chars and any(units for _, units in sections):
        oldest = min((units[0].at, index) for index, (_, units) in enumerate(sections) if units)
        sections[oldest[1]][1].pop(0)
        drops[Drop.SECTIONS_BUDGET] += 1


def build_input(
    tasks: Iterable[TaskItem],
    activity: Iterable[ActivityItem],
    *,
    as_of: datetime.datetime,
    seed: int,
    views: Iterable[ViewItem] = (),
    limits: RenderLimits = DEFAULT_LIMITS,
    parents: ParentLookup | None = None,
) -> RenderedInput | None:
    """The rendered input of one (project, person) pair, or None when nothing survives the filters.

    Order: the named filters, then the burst cap, then the recency-weighted sample, then the hard
    budget, so the sample is drawn from clean units only. `parents` groups activity lines under the
    objects that hold them. The views section shows its lines grouped by type after the budget,
    because the budget drops the oldest unit of a section first."""
    drops: Counter[str] = Counter()
    activity = list(activity)
    task_pool = burst_cap(dedupe_latest(task_units(tasks, drops, limits), drops), drops, limits.max_units_per_day)
    capped_before = drops[Drop.SAMPLE_CAP] + drops[Drop.BURST_CAP]
    activity_lines = activity_units(activity, drops, parents, limits)
    # Lines that `activity_units` dropped for its line cap or its per-day cap.
    activity_pool = len(activity_lines) + drops[Drop.SAMPLE_CAP] + drops[Drop.BURST_CAP] - capped_before
    view_lines = view_units(views, activity, drops, limits)
    if not task_pool and not activity_lines and not view_lines:
        return None
    chosen_tasks = sample_units(task_pool, limit=limits.task_lines, as_of=as_of, seed=seed)
    drops[Drop.SAMPLE_CAP] += len(task_pool) - len(chosen_tasks)
    sections = [(TASKS_HEADER, chosen_tasks), (ACTIVITY_HEADER, activity_lines), (VIEWS_HEADER, view_lines)]
    enforce_budget(sections, drops, limits.sections_max_chars)
    sections[2] = (VIEWS_HEADER, sorted(sections[2][1], key=lambda unit: unit.text))
    rendered = [_section(header, units) for header, units in sections]
    text = "\n\n".join(part for part in rendered if part)
    return RenderedInput(
        text=text,
        n_tasks=len(sections[0][1]),
        n_activity_lines=len(sections[1][1]),
        n_view_lines=len(sections[2][1]),
        task_chars=len(rendered[0]),
        activity_chars=len(rendered[1]),
        view_chars=len(rendered[2]),
        input_chars=len(text),
        input_tokens_estimate=estimate_tokens(len(text)),
        drops={str(reason): count for reason, count in sorted(drops.items()) if count},
        task_pool=len(task_pool),
        activity_pool=activity_pool,
    )
