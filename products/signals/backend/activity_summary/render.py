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
import functools
import dataclasses
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from posthog.dataclasses import frozen

# Bump on any code change to the filters, the default caps, the sampling or the rendered layout, so summaries
# stay comparable. Limits from the flag payload go into `inputs_used` instead.
RENDER_VERSION = 10

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
ACTIVITY_LINE_CHARS = 300
ACTIVITY_NAME_CHARS = 70
ACTIVITY_INTENT_CHARS = 160
# Distinct agent intents one collapsed line keeps, newest first. They share ACTIVITY_INTENT_CHARS.
ACTIVITY_MAX_INTENTS = 2
VIEW_LINE_CHARS = 160
MCP_LINES = 10
MCP_LINE_CHARS = 480
MCP_CHAIN_MAX_INTENTS = 4
# The MCP intent buffer cuts an intent to this many characters.
MCP_INTENT_CHARS = 200
# An intent on a long chain keeps at least this many characters, even when the line cap then cuts the chain.
MIN_MCP_INTENT_CHARS = 60
# An agent can keep one MCP session open all day. A longer pause between two calls starts a new line.
MCP_SESSION_IDLE_GAP = datetime.timedelta(minutes=30)
# Intents that open with the same text keep it on the first intent only, if the shared text is at least this long.
MIN_SHARED_OPENING_CHARS = 20
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
MCP_HEADER = "What the person's AI agent looked into for them over MCP (one line per session; intents in order):"
MCP_CHAIN_SEPARATOR = " --> "

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
# Long runs of word characters. A run that mixes letters and digits is masked when one segment looks like
# an API key, session token or hash, or when a long run does not read as a name. The checks run in
# `_mask_token`, because lookaheads in the pattern rescan the run at every word boundary inside it and
# take quadratic time on a long input.
_WORD_RUN = re.compile(r"[\w-]{16,}")
_RUN_SEPARATORS = re.compile(r"[-_]")
MIN_SECRET_SEGMENT_CHARS = 16
# Masking is the default for a run this long, because a URL-safe credential can have only short segments.
MIN_SECRET_RUN_CHARS = 24
# A name such as "new-onboarding-flow-q4-2026" has few segments with digits, and they are short.
MAX_NAME_DIGIT_SEGMENTS = 2
MAX_NAME_DIGIT_SEGMENT_CHARS = 4
# UUID segments are shorter than `MIN_SECRET_SEGMENT_CHARS`, so they have their own pattern.
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[A-Za-z]")
# A name that is only masks, digits and punctuation after `clean_text` names nothing.
_MEANINGLESS_NAME = re.compile(r"(?:<token>|<email>|\d|[^\w<>]|_)*")
_WHITESPACE = re.compile(r"\s+")

# Inbox onboarding creates a scout config for each canonical scout, named after its skill.
ONBOARDING_CONFIG_SCOPES: frozenset[str] = frozenset({"SignalScoutConfig"})
CANONICAL_SCOUT_PREFIX = "signals-scout-"
# Personal API key changes are account housekeeping, not work in the project.
API_KEY_SCOPES: frozenset[str] = frozenset({"PersonalAPIKey"})
# CI writes deploy markers as annotations through a personal API key.
ANNOTATION_SCOPE = "Annotation"
PERSONAL_API_KEY_CREDENTIAL = "personal_api_key"
# Project settings live on both scopes.
TEAM_SETTINGS_SCOPES: frozenset[str] = frozenset({"Team", "Project"})
# Team settings rows without an intent are dropped when the person has at least this many: one change
# can be deliberate, but repeated ones come from setup flows.
MIN_TEAM_SETTINGS_ROWS = 2
TICKET_SCOPE = "Ticket"
# Setup chores, such as Inbox settings, integrations and their diagnostics, are not work in the project.
SETUP_SCOPES: frozenset[str] = frozenset({"SignalTeamConfig", "Integration", "ProjectSecretAPIKey", "ExportedAsset"})
# Person deletes come from data cleanup, such as removing test users.
PERSON_SCOPE = "Person"
# Changes to this many distinct tickets on one UTC day collapse to one line with a count.
MIN_TICKET_BURST = 3
# Changes of one kind to this many distinct objects of one type inside the window are a bulk job,
# such as knowledge sources synced for many accounts.
MIN_BULK_OBJECTS = 10
BULK_WINDOW = datetime.timedelta(hours=1)
# A task goal seen on this many distinct days is a scheduled job, not a question the person asked.
MIN_REPEATED_TASK_DAYS = 4
# The MCP routes an agent calls to orient itself: the current user, project and organization, and skills.
MCP_PLUMBING_ROUTES: frozenset[str] = frozenset(
    {
        "users-detail",
        "projects-detail",
        "projects-list",
        "project_environments-detail",
        "organizations-detail",
        "organizations-list",
    }
)
MCP_PLUMBING_ROUTE_PREFIXES: tuple[str, ...] = ("project_llm_skills-", "project_community_skills-")
# The same chain of intents in this many sessions of the window is a scheduled job, not a person.
MIN_REPEATED_MCP_CHAINS = 4
_DIGITS = re.compile(r"\d+")
_CAMEL_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


class Product(StrEnum):
    """The fixed product keys of an activity summary. Scene views and activity scopes map to these only."""

    PRODUCT_ANALYTICS = "product_analytics"
    DASHBOARDS = "dashboards"
    WEB_ANALYTICS = "web_analytics"
    SESSION_REPLAY = "session_replay"
    HEATMAPS = "heatmaps"
    ERROR_TRACKING = "error_tracking"
    EXPERIMENTS = "experiments"
    FEATURE_FLAGS = "feature_flags"
    EARLY_ACCESS_FEATURES = "early_access_features"
    SURVEYS = "surveys"
    PRODUCT_TOURS = "product_tours"
    NOTEBOOKS = "notebooks"
    COHORTS = "cohorts"
    PERSONS = "persons"
    DATA_MANAGEMENT = "data_management"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_PIPELINES = "data_pipelines"
    WORKFLOWS = "workflows"
    AI_OBSERVABILITY = "ai_observability"
    MCP_ANALYTICS = "mcp_analytics"
    LOGS = "logs"
    TRACING = "tracing"
    ENDPOINTS = "endpoints"
    REVENUE_ANALYTICS = "revenue_analytics"
    CUSTOMER_ANALYTICS = "customer_analytics"
    INBOX = "inbox"
    CANVASES = "canvases"
    SUPPORT = "support"


# A view log row of this type records a page, and its ref is the frontend scene id.
SCENE_VIEW_TYPE = "scene"
# The product of each scene id prefix, and its label in the prompt. A prefix matches its plural and any
# longer scene id of the same product, such as "ErrorTrackingIssue". Other scenes, such as settings,
# the home page or a new tab, say nothing about the work.
_SCENE_PRODUCTS: tuple[tuple[str, Product, str], ...] = (
    ("Insight|SavedInsight|ProductAnalytics", Product.PRODUCT_ANALYTICS, "Product analytics"),
    ("Dashboard", Product.DASHBOARDS, "Dashboards"),
    ("WebAnalytics", Product.WEB_ANALYTICS, "Web analytics"),
    ("Replay|SessionRecording|SessionSummaries", Product.SESSION_REPLAY, "Session replay"),
    ("Heatmap", Product.HEATMAPS, "Heatmaps"),
    ("ErrorTracking", Product.ERROR_TRACKING, "Error tracking"),
    ("Experiment", Product.EXPERIMENTS, "Experiments"),
    ("FeatureFlag", Product.FEATURE_FLAGS, "Feature flags"),
    ("EarlyAccessFeature", Product.EARLY_ACCESS_FEATURES, "Early access features"),
    ("Survey", Product.SURVEYS, "Surveys"),
    ("ProductTour", Product.PRODUCT_TOURS, "Product tours"),
    ("Notebook", Product.NOTEBOOKS, "Notebooks"),
    ("Cohort", Product.COHORTS, "Cohorts"),
    ("Person|Group", Product.PERSONS, "Persons and groups"),
    ("Action|EventDefinition|PropertyDefinition|DataManagement", Product.DATA_MANAGEMENT, "Data management"),
    ("SQLEditor|DataWarehouse|Sources|Models", Product.DATA_WAREHOUSE, "Data warehouse"),
    ("Pipeline|Destination|Transformation|HogFunction|BatchExport", Product.DATA_PIPELINES, "Data pipelines"),
    ("Workflow|Broadcast", Product.WORKFLOWS, "Workflows"),
    ("AIObservability", Product.AI_OBSERVABILITY, "AI observability"),
    ("MCPAnalytics", Product.MCP_ANALYTICS, "MCP analytics"),
    ("Logs", Product.LOGS, "Logs"),
    ("Tracing", Product.TRACING, "Tracing"),
    ("Endpoint", Product.ENDPOINTS, "Endpoints"),
    ("RevenueAnalytics", Product.REVENUE_ANALYTICS, "Revenue analytics"),
    ("CustomerAnalytics", Product.CUSTOMER_ANALYTICS, "Customer analytics"),
    ("Inbox", Product.INBOX, "Inbox"),
    ("Canvas", Product.CANVASES, "Canvases"),
    ("SupportTicket", Product.SUPPORT, "Support"),
)
# Activity log scopes that no scene id prefix covers. A scope otherwise maps like a scene id.
_SCOPE_PRODUCTS: tuple[tuple[str, Product], ...] = (
    ("HogFlow", Product.WORKFLOWS),
    ("ExternalData", Product.DATA_WAREHOUSE),
    ("Plugin", Product.DATA_PIPELINES),
    ("LLM|Evaluation", Product.AI_OBSERVABILITY),
    ("Log", Product.LOGS),
    ("Signal", Product.INBOX),
    ("Ticket", Product.SUPPORT),
)


def _prefix_pattern(prefixes: str) -> re.Pattern[str]:
    return re.compile(rf"^(?:{prefixes})s?(?:[A-Z]|$)")


_SCENE_PATTERNS: tuple[tuple[re.Pattern[str], Product], ...] = tuple(
    (_prefix_pattern(prefixes), product) for prefixes, product, _ in _SCENE_PRODUCTS
)
_SCOPE_PATTERNS: tuple[tuple[re.Pattern[str], Product], ...] = _SCENE_PATTERNS + tuple(
    (_prefix_pattern(prefixes), product) for prefixes, product in _SCOPE_PRODUCTS
)
PRODUCT_LABELS: Mapping[Product, str] = {product: label for _, product, label in _SCENE_PRODUCTS}


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
    activity_max_intents: int = _limit(ACTIVITY_MAX_INTENTS, max_value=10)
    profile_max_chars: int = _limit(PROFILE_MAX_CHARS, max_value=20000)
    max_completion_tokens: int = _limit(MAX_COMPLETION_TOKENS, max_value=16000)
    mcp_lines: int = _limit(MCP_LINES, max_value=50)
    mcp_line_chars: int = _limit(MCP_LINE_CHARS, max_value=1000)
    mcp_chain_max_intents: int = _limit(MCP_CHAIN_MAX_INTENTS, max_value=20)


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
    ONBOARDING_SCOUT_CONFIG = "onboarding_scout_config"
    API_KEY_CHANGE = "api_key_change"
    API_KEY_ANNOTATION = "api_key_annotation"
    TEAM_SETTINGS = "team_settings"
    SETUP_SCOPE = "setup_scope"
    BULK_SAME_TYPE = "bulk_same_type"
    TICKET_BURST = "ticket_burst"
    REPEATED_TASK = "repeated_task"
    GENERIC_SCENE = "generic_scene"
    DUPLICATE = "duplicate"
    GROUPED_INTO_PARENT = "grouped_into_parent"
    BURST_CAP = "burst_cap"
    SAMPLE_CAP = "sample_cap"
    SECTIONS_BUDGET = "sections_budget"
    EXCLUDED_PRODUCT = "excluded_product"
    MCP_PLUMBING_ROUTE = "mcp_plumbing_route"
    MCP_IN_ACTIVITY = "mcp_in_activity"
    MCP_THIN_SESSION = "mcp_thin_session"
    MCP_REPEATED_CHAIN = "mcp_repeated_chain"


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
    # The credential that authenticated the change, such as "personal_api_key". None outside a request.
    credential_type: str | None = None
    # The short id in the row's detail. The file system refers to some objects, such as insights, by it.
    short_id: str | None = None


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
class McpItem:
    """One MCP call of the person's agent, with the intent the agent stated, from the MCP intent buffer.

    `session_id` and `route_name` can be empty."""

    at: datetime.datetime
    session_id: str
    route_name: str
    intent: str


@frozen
class Unit:
    """One rendered line, dated by its latest activity."""

    at: datetime.datetime
    text: str
    # Characters of agent intent on the line.
    intent_chars: int = 0
    intent_keys: frozenset[str] = frozenset()


@frozen
class _ActivityLine:
    """A rendered activity line with the fields that rank it."""

    at: datetime.datetime
    text: str
    created: bool
    rows: int
    intent_chars: int = 0
    intent_keys: frozenset[str] = frozenset()


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
    # Activity lines that carry at least one agent intent, and the intent characters on them.
    intent_lines: int = 0
    intent_chars: int = 0
    n_mcp_lines: int = 0
    mcp_chars: int = 0
    # MCP sessions that passed the named filters, before the caps.
    mcp_pool: int = 0
    # Products whose pages the person opened. They render in the computed block, not here, but count as units.
    n_page_units: int = 0

    @property
    def units(self) -> int:
        return self.n_tasks + self.n_activity_lines + self.n_view_lines + self.n_mcp_lines + self.n_page_units


def _reads_as_name(segments: Sequence[str]) -> bool:
    with_digits = [segment for segment in segments if _DIGIT.search(segment)]
    if len(with_digits) > MAX_NAME_DIGIT_SEGMENTS:
        return False
    if any(len(segment) > MAX_NAME_DIGIT_SEGMENT_CHARS for segment in with_digits):
        return False
    # Random URL-safe text mixes cases inside a segment. The words of a name do not.
    return all(segment in (segment.lower(), segment.upper(), segment.capitalize()) for segment in segments)


def _mask_token(match: re.Match[str]) -> str:
    run = match.group()
    if not (_DIGIT.search(run) and _LETTER.search(run)):
        return run
    segments = _RUN_SEPARATORS.split(run)
    for segment in segments:
        if len(segment) >= MIN_SECRET_SEGMENT_CHARS and _DIGIT.search(segment) and _LETTER.search(segment):
            return "<token>"
    if len(run) >= MIN_SECRET_RUN_CHARS and not _reads_as_name(segments):
        return "<token>"
    return run


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
    text = _UUID.sub("<token>", text)
    text = _WORD_RUN.sub(_mask_token, text)
    return _WHITESPACE.sub(" ", text).strip()[:max_chars].strip()


def cap_line(text: str, max_chars: int) -> str:
    """Cut at a word boundary and mark the cut."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


def intent_key(intent: str) -> str:
    """An agent intent as both sources compare it. The activity log and the MCP buffer cut it at different lengths."""
    return clean_text(intent, MCP_INTENT_CHARS).casefold()


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


def _goal_key(text: str) -> str:
    """A task goal without its numbers and case, so the runs of one scheduled job compare equal."""
    return _DIGITS.sub("#", text.lower())


def _collapse_repeated(units: Sequence[Unit], drops: Counter[str]) -> list[Unit]:
    """One line with a count for each goal seen on `MIN_REPEATED_TASK_DAYS` or more distinct days."""
    by_goal: dict[str, list[Unit]] = {}
    for unit in units:
        by_goal.setdefault(_goal_key(unit.text.split(" ", 2)[-1]), []).append(unit)
    collapsed: list[Unit] = []
    for group in by_goal.values():
        if len({_day(unit.at) for unit in group}) < MIN_REPEATED_TASK_DAYS:
            collapsed.extend(group)
            continue
        latest = max(group, key=lambda unit: unit.at)
        collapsed.append(Unit(at=latest.at, text=f"{latest.text} (x{len(group)})"))
        drops[Drop.REPEATED_TASK] += len(group) - 1
    return collapsed


def task_units(tasks: Iterable[TaskItem], drops: Counter[str], limits: RenderLimits = DEFAULT_LIMITS) -> list[Unit]:
    """One line per task, with templated titles collapsed to one line per template and a goal repeated
    on many days collapsed to one line with a count."""
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
    units = _collapse_repeated(units, drops)
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


def _intent_text(rows: Iterable[ActivityItem], limits: RenderLimits) -> tuple[str, frozenset[str]]:
    """Up to `limits.activity_max_intents` distinct intents of the rows, newest first, in one shared budget,
    and the `intent_key` of each.

    The budget is at most half the line, so the head of the line always keeps some room."""
    max_chars = min(limits.activity_intent_chars, limits.activity_line_chars // 2)
    distinct: dict[str, str] = {}
    keys: set[str] = set()
    for row in sorted(rows, key=lambda row: row.at, reverse=True):
        if len(distinct) >= limits.activity_max_intents:
            break
        text = clean_text(row.intent or "", max_chars * 2)
        if text:
            distinct.setdefault(text.casefold(), text)
            keys.add(intent_key(row.intent or ""))
    return cap_line("; ".join(distinct.values()), max_chars), frozenset(keys)


def _activity_line(head: str, rows: Sequence[ActivityItem], limits: RenderLimits, *, created: bool) -> _ActivityLine:
    """The head cut to the room that the agent intents leave, so a long name cannot push the intents out."""
    intent, keys = _intent_text(rows, limits)
    suffix = f" (agent: {intent})" if intent else ""
    head = cap_line(head, max(limits.activity_line_chars - len(suffix), 1))
    return _ActivityLine(
        at=max(row.at for row in rows),
        text=cap_line(head + suffix, limits.activity_line_chars),
        created=created,
        rows=len(rows),
        intent_chars=len(intent),
        intent_keys=keys,
    )


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


def _day_span(rows: Sequence[ActivityItem]) -> str:
    """The UTC day of the rows, or the first and the last day when they span more than one."""
    first, last = _day(min(row.at for row in rows)), _day(max(row.at for row in rows))
    return last.isoformat() if first == last else f"{first.isoformat()} to {last.isoformat()}"


def _object_line(
    scope: str, activity: str, name: str, rows: Sequence[ActivityItem], context: str, limits: RenderLimits
) -> _ActivityLine:
    count = f" (x{len(rows)})" if len(rows) > 1 else ""
    line = f'- {_day_span(rows)} {activity} {scope} "{_display_name(name)}"{context}{count}'
    return _activity_line(line, rows, limits, created=activity == "created")


def _group_line(
    parent: Parent,
    own: Sequence[ObjectKey],
    children: Sequence[ObjectKey],
    collapsed: Mapping[ObjectKey, list[ActivityItem]],
    limits: RenderLimits,
) -> _ActivityLine:
    """One line for a parent and the children merged into it, children ranked like lines."""
    rows = [row for key in (*own, *children) for row in collapsed[key]]
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
    head = f"- {_day_span(rows)} {head}"
    intent, _ = _intent_text(rows, limits)
    suffix_chars = len(f" (agent: {intent})") if intent else 0
    line = head + _quoted_names(names, limits.activity_line_chars - len(head) - suffix_chars)
    return _activity_line(line, rows, limits, created=any(row.activity == "created" for row in rows))


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


def is_auto_named(name: str) -> bool:
    return _AUTO_NAME.search(name) is not None


# Every `person_activity` call checks each row, and a window repeats the same names many times.
@functools.lru_cache(maxsize=4096)
def is_unnamed(name: str) -> bool:
    """True for an empty name, and for a name that is only masks or digits once `clean_text` masks it."""
    return _MEANINGLESS_NAME.fullmatch(clean_text(name, ACTIVITY_NAME_CHARS * 2)) is not None


def _has_intent(item: ActivityItem) -> bool:
    return bool(item.intent and item.intent.strip())


def _row_drop(item: ActivityItem) -> Drop | None:
    """The rule that drops one activity row on its own, or None when nothing on the row says it is not the person's."""
    name = (item.name or "").strip()
    if item.scope in NOISY_ACTIVITY_SCOPES:
        return Drop.NOISY_SCOPE
    if (item.client or "").startswith(SCOUT_CLIENT_PREFIX):
        return Drop.SCOUT_CLIENT
    if item.scope in API_KEY_SCOPES:
        return Drop.API_KEY_CHANGE
    if item.scope == ANNOTATION_SCOPE and item.credential_type == PERSONAL_API_KEY_CREDENTIAL:
        return Drop.API_KEY_ANNOTATION
    if item.scope in ONBOARDING_CONFIG_SCOPES and name.startswith(CANONICAL_SCOUT_PREFIX) and not _has_intent(item):
        return Drop.ONBOARDING_SCOUT_CONFIG
    is_setup = item.scope in SETUP_SCOPES or (item.scope == PERSON_SCOPE and item.activity == "deleted")
    if is_setup and not _has_intent(item):
        return Drop.SETUP_SCOPE
    if is_unnamed(name):
        return Drop.UNNAMED_OBJECT
    if _AUTO_NAME.search(name):
        return Drop.AUTO_NAMED_OBJECT
    return None


def _plural_label(scope: str, count: int) -> str:
    """A scope in lower-case words, such as "knowledge sources" for "KnowledgeSource"."""
    words = " ".join(word.lower() for word in _CAMEL_WORD.findall(scope))
    return words if count == 1 else f"{words}s"


def _object_id(item: ActivityItem) -> str:
    return item.item_id or (item.name or "").strip()


def _count_line(rows: Sequence[ActivityItem], text: str, limits: RenderLimits) -> _ActivityLine:
    latest = max(row.at for row in rows)
    return _activity_line(f"- {_day(latest).isoformat()} {text}", rows, limits, created=False)


@frozen
class _TicketBursts:
    other_rows: list[ActivityItem]
    lines: list[_ActivityLine]
    burst_rows: list[ActivityItem]


def _collapse_tickets(items: Sequence[ActivityItem], drops: Counter[str], limits: RenderLimits) -> _TicketBursts:
    """One counted line for each UTC day and kind of change that touches `MIN_TICKET_BURST` or more tickets."""
    groups: dict[tuple[datetime.date, str], list[ActivityItem]] = {}
    for item in items:
        if item.scope == TICKET_SCOPE and item.activity != "created":
            groups.setdefault((_day(item.at), item.activity), []).append(item)
    burst: set[int] = set()
    lines: list[_ActivityLine] = []
    for (_, activity), rows in groups.items():
        tickets = len({_object_id(row) for row in rows})
        if tickets < MIN_TICKET_BURST:
            continue
        burst.update(id(row) for row in rows)
        lines.append(_count_line(rows, f"{activity} {tickets} support tickets", limits))
        drops[Drop.TICKET_BURST] += len(rows) - 1
    return _TicketBursts(
        other_rows=[item for item in items if id(item) not in burst],
        lines=lines,
        burst_rows=[item for item in items if id(item) in burst],
    )


def _bulk_runs(rows: Sequence[ActivityItem]) -> list[list[ActivityItem]]:
    """The runs of rows inside one `BULK_WINDOW` that touch `MIN_BULK_OBJECTS` or more distinct objects."""
    ordered = sorted(rows, key=lambda row: row.at)
    runs: list[list[ActivityItem]] = []
    start = 0
    while start < len(ordered):
        end = start
        while end < len(ordered) and ordered[end].at - ordered[start].at <= BULK_WINDOW:
            end += 1
        if len({_object_id(row) for row in ordered[start:end]}) >= MIN_BULK_OBJECTS:
            runs.append(ordered[start:end])
            start = end
        else:
            start += 1
    return runs


def _collapse_bulk(
    items: Sequence[ActivityItem], drops: Counter[str], limits: RenderLimits
) -> tuple[list[ActivityItem], list[_ActivityLine]]:
    """A bulk job's rows as one counted line when an agent stated why, and dropped when nothing did.

    Creates are left alone: the parent grouping already merges a dashboard built in one go."""
    groups: dict[tuple[str, str], list[ActivityItem]] = {}
    for item in items:
        if item.activity != "created":
            groups.setdefault((item.scope, item.activity), []).append(item)
    bulk: set[int] = set()
    lines: list[_ActivityLine] = []
    for (scope, activity), rows in groups.items():
        for run in _bulk_runs(rows):
            bulk.update(id(row) for row in run)
            if any(_has_intent(row) for row in run):
                objects = len({_object_id(row) for row in run})
                lines.append(_count_line(run, f"{activity} {objects} {_plural_label(scope, objects)}", limits))
                drops[Drop.BULK_SAME_TYPE] += len(run) - 1
            else:
                drops[Drop.BULK_SAME_TYPE] += len(run)
    return [item for item in items if id(item) not in bulk], lines


def _drop_team_settings(items: Sequence[ActivityItem], drops: Counter[str]) -> list[ActivityItem]:
    """Without the team settings rows that state no intent, when there are `MIN_TEAM_SETTINGS_ROWS` or more."""
    unstated = [item for item in items if item.scope in TEAM_SETTINGS_SCOPES and not _has_intent(item)]
    if len(unstated) < MIN_TEAM_SETTINGS_ROWS:
        return list(items)
    drops[Drop.TEAM_SETTINGS] += len(unstated)
    dropped = {id(item) for item in unstated}
    return [item for item in items if id(item) not in dropped]


def person_activity(
    items: Iterable[ActivityItem],
    drops: Counter[str],
    limits: RenderLimits = DEFAULT_LIMITS,
    keep_ticket_bursts: bool = False,
) -> tuple[list[ActivityItem], list[_ActivityLine]]:
    """The rows that are the person's own work, and one counted line for each ticket burst or bulk job.

    The row rules run first, then the ticket bursts, so a ticket burst is not taken for a bulk job.
    With `keep_ticket_bursts`, the rows of each ticket burst stay in the result as well: a burst is
    one line in the prompt, but each ticket is still the person's work."""
    kept: list[ActivityItem] = []
    for item in items:
        if (reason := _row_drop(item)) is not None:
            drops[reason] += 1
        else:
            kept.append(item)
    tickets = _collapse_tickets(kept, drops, limits)
    kept, bulk_lines = _collapse_bulk(tickets.other_rows, drops, limits)
    kept = _drop_team_settings(kept, drops)
    return (kept + tickets.burst_rows if keep_ticket_bursts else kept), tickets.lines + bulk_lines


def activity_units(
    items: Iterable[ActivityItem],
    drops: Counter[str],
    parents: ParentLookup | None = None,
    limits: RenderLimits = DEFAULT_LIMITS,
) -> list[Unit]:
    """Changes collapsed to one line per object, or per parent, creates first, then the most changed, then the newest.

    A line carries the newest distinct agent intents of its rows, up to `limits.activity_max_intents`. A day keeps at most `limits.max_activity_lines_per_day`
    lines while other days have lines left, not the `MAX_UNITS_PER_DAY` of tasks: lines are already
    collapsed per object, and a busy day of changes to different objects is more than three things."""
    kept, count_lines = person_activity(items, drops, limits)
    collapsed: dict[ObjectKey, list[ActivityItem]] = {}
    for item in kept:
        collapsed.setdefault((item.scope, item.activity, (item.name or "").strip()), []).append(item)
    lines = _lines_with_parents(collapsed, parents or {}, drops, limits) + count_lines
    ranked = sorted(lines, key=lambda line: (not line.created, -line.rows, -line.at.timestamp(), line.text))
    kept_lines = _spread_across_days(ranked, drops, limits)
    return sorted(
        (
            Unit(at=line.at, text=line.text, intent_chars=line.intent_chars, intent_keys=line.intent_keys)
            for line in kept_lines
        ),
        key=lambda unit: (unit.at, unit.text),
    )


def _match_product(patterns: Sequence[tuple[re.Pattern[str], Product]], name: str) -> Product | None:
    for pattern, product in patterns:
        if pattern.match(name):
            return product
    return None


def scene_product(scene_id: str) -> Product | None:
    return _match_product(_SCENE_PATTERNS, scene_id)


def scope_product(scope: str) -> Product | None:
    """The product of an activity log scope, such as "FeatureFlag", or of a file system type."""
    return _match_product(_SCOPE_PATTERNS, scope)


def scope_of(view_type: str) -> str:
    """The activity log scope of a file system type, such as "FeatureFlag" for "feature_flag"."""
    return "".join(word.capitalize() for word in view_type.split("/")[0].split("_"))


def view_product(view: ViewItem) -> Product | None:
    if view.type == SCENE_VIEW_TYPE:
        return scene_product(view.ref)
    return scope_product(scope_of(view.type))


def without_products(
    activity: Iterable[ActivityItem],
    views: Iterable[ViewItem],
    products: frozenset[Product],
    drops: Counter[str],
) -> tuple[list[ActivityItem], list[ViewItem]]:
    """The activity rows and views whose product is not in `products`. Tasks have no product, so they stay."""
    kept_activity: list[ActivityItem] = []
    for item in activity:
        if scope_product(item.scope) in products:
            drops[Drop.EXCLUDED_PRODUCT] += 1
        else:
            kept_activity.append(item)
    kept_views: list[ViewItem] = []
    for view in views:
        if view_product(view) in products:
            drops[Drop.EXCLUDED_PRODUCT] += 1
        else:
            kept_views.append(view)
    return kept_activity, kept_views


def days_text(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def page_products(views: Iterable[ViewItem], drops: Counter[str]) -> set[Product]:
    """The products of the opened scenes. The "p" lines of the computed block show them, so they get no view line."""
    products: set[Product] = set()
    for view in views:
        if view.type != SCENE_VIEW_TYPE:
            continue
        if (product := scene_product(view.ref)) is None:
            drops[Drop.GENERIC_SCENE] += 1
        else:
            products.add(product)
    return products


def view_units(
    views: Iterable[ViewItem],
    activity: Iterable[ActivityItem],
    drops: Counter[str],
    limits: RenderLimits = DEFAULT_LIMITS,
) -> list[Unit]:
    """One line per opened object, the most opened first. Scenes are in `page_products`.

    An object line also counts the days the person edited it, matched to their activity rows by
    scope and name. These lines skip the per-day burst cap."""
    edit_days: dict[tuple[str, str], set[datetime.date]] = {}
    for item in person_activity(activity, Counter(), limits)[0]:
        edit_days.setdefault((item.scope, (item.name or "").strip()), set()).add(_day(item.at))
    ranked: list[tuple[int, datetime.datetime, str]] = []
    for view in views:
        if view.type == SCENE_VIEW_TYPE:
            continue
        name = (view.name or "").strip()
        if is_unnamed(name):
            drops[Drop.UNNAMED_OBJECT] += 1
            continue
        if _AUTO_NAME.search(name):
            drops[Drop.AUTO_NAMED_OBJECT] += 1
            continue
        opened = len(set(view.days))
        name_text = cap_line(clean_text(name, ACTIVITY_NAME_CHARS * 2), ACTIVITY_NAME_CHARS)
        facts = [f"opened {days_text(opened)}", f"last {_day(view.at).isoformat()}"]
        if edited := len(edit_days.get((scope_of(view.type), name), ())):
            facts.append(f"edited {days_text(edited)}")
        if view.not_theirs:
            facts.append("not theirs")
        label = view.type.split("/")[0].replace("_", " ").capitalize()
        ranked.append((opened, view.at, f'- {label} "{name_text}": {", ".join(facts)}'))
    ranked.sort(key=lambda entry: (-entry[0], -entry[1].timestamp(), entry[2]))
    if len(ranked) > limits.view_lines:
        drops[Drop.SAMPLE_CAP] += len(ranked) - limits.view_lines
    units = [Unit(at=at, text=cap_line(text, limits.view_line_chars)) for _, at, text in ranked[: limits.view_lines]]
    return sorted(units, key=lambda unit: (unit.at, unit.text))


def _is_plumbing_route(route_name: str) -> bool:
    return route_name in MCP_PLUMBING_ROUTES or route_name.startswith(MCP_PLUMBING_ROUTE_PREFIXES)


@frozen
class _McpSession:
    """The intents of one MCP session, in order, dated by its latest call."""

    at: datetime.datetime
    calls: int
    chain: tuple[str, ...]


def _split_on_idle(calls: list[McpItem]) -> list[list[McpItem]]:
    """The calls in time order, in runs that no pause of more than `MCP_SESSION_IDLE_GAP` interrupts."""
    calls = sorted(calls, key=lambda call: call.at)
    runs = [calls[:1]]
    for previous, call in zip(calls, calls[1:]):
        if call.at - previous.at > MCP_SESSION_IDLE_GAP:
            runs.append([])
        runs[-1].append(call)
    return runs


def _shared_opening(first: str, other: str) -> int:
    """The length of the whole words that open both texts, or 0 when they are shorter than `MIN_SHARED_OPENING_CHARS`."""
    end = 0
    while end < min(len(first), len(other)) and first[end].casefold() == other[end].casefold():
        end += 1
    if not ((end == len(first) or first[end] == " ") and (end == len(other) or other[end] == " ")):
        end = max(first.rfind(" ", 0, end), 0)
    return end if end >= MIN_SHARED_OPENING_CHARS else 0


def _distinct_chain(intents: Iterable[str]) -> tuple[str, ...]:
    """The intents without repeats, and without the opening that later intents share with the first one."""
    chain: list[str] = []
    seen: set[str] = set()
    for intent in intents:
        if chain:
            intent = intent[_shared_opening(chain[0], intent) :].lstrip(" ,;:.-–—").strip()
        if intent and intent.casefold() not in seen:
            seen.add(intent.casefold())
            chain.append(intent)
    return tuple(chain)


def _mcp_sessions(records: Iterable[McpItem], shown_intents: frozenset[str], drops: Counter[str]) -> list[_McpSession]:
    """The records grouped by session, without plumbing routes and the intents that `shown_intents` holds.

    A record without a session id is its own session, and a long pause splits a session in two."""
    grouped: dict[tuple[str, int], list[McpItem]] = {}
    for index, record in enumerate(records):
        if _is_plumbing_route(record.route_name):
            drops[Drop.MCP_PLUMBING_ROUTE] += 1
            continue
        grouped.setdefault((record.session_id, -1) if record.session_id else ("", index), []).append(record)
    sessions: list[_McpSession] = []
    for run in (run for calls in grouped.values() for run in _split_on_idle(calls)):
        intents: list[str] = []
        for call in run:
            text = _SUMMARY_LABEL.sub("", clean_text(call.intent, MCP_INTENT_CHARS))
            if not text:
                continue
            if intent_key(call.intent) in shown_intents:
                drops[Drop.MCP_IN_ACTIVITY] += 1
                continue
            intents.append(text)
        chain = _distinct_chain(intents)
        if not chain:
            drops[Drop.MCP_THIN_SESSION] += 1
            continue
        sessions.append(_McpSession(at=run[-1].at, calls=len(run), chain=chain))
    return sessions


def _shorten_chain(chain: Sequence[str], max_intents: int) -> list[str]:
    """The first and last intents and the longest ones between them, in order, with "…" where intents were left out."""
    if len(chain) <= max_intents:
        return list(chain)
    middle = sorted(range(1, len(chain) - 1), key=lambda index: (-len(chain[index]), index))
    kept = sorted([0, len(chain) - 1, *middle[: max(max_intents - 2, 0)]])
    shortened = [chain[kept[0]]]
    for previous, index in zip(kept, kept[1:]):
        if index - previous > 1:
            shortened.append("…")
        shortened.append(chain[index])
    return shortened


def _intent_room(lengths: Sequence[int], budget: int) -> int:
    """The longest an intent may be, so the intents fit the budget. Short intents leave their unused share to long ones."""
    room = budget
    for remaining, length in enumerate(sorted(lengths)):
        share = budget // (len(lengths) - remaining)
        if length > share:
            room = share
            break
        budget -= length
    return max(room, MIN_MCP_INTENT_CHARS)


def _mcp_line(session: _McpSession, limits: RenderLimits) -> str:
    """The session's intents in order. A long chain keeps its first, its last and its longest intents."""
    chain = _shorten_chain(session.chain, limits.mcp_chain_max_intents)
    calls = "1 call" if session.calls == 1 else f"{session.calls} calls"
    head = f"- {_day(session.at).isoformat()}, {calls}: "
    intents = [intent for intent in chain if intent != "…"]
    fixed = len(head) + len(MCP_CHAIN_SEPARATOR) * (len(chain) - 1) + len("…") * (len(chain) - len(intents))
    # A cap on each intent, so a long first intent cannot push the last one out.
    room = _intent_room([len(intent) for intent in intents], limits.mcp_line_chars - fixed)
    return cap_line(head + MCP_CHAIN_SEPARATOR.join(cap_line(intent, room) for intent in chain), limits.mcp_line_chars)


def mcp_units(
    records: Iterable[McpItem],
    activity_lines: Iterable[Unit],
    drops: Counter[str],
    limits: RenderLimits = DEFAULT_LIMITS,
) -> list[Unit]:
    """One line per MCP session of the person's agent, with the distinct intents it stated in order.

    An intent that an activity line already shows goes, so a write does not show twice. A chain that
    repeats in `MIN_REPEATED_MCP_CHAINS` or more sessions is a scheduled job, and all its sessions go."""
    shown = frozenset(key for unit in activity_lines for key in unit.intent_keys)
    sessions = _mcp_sessions(records, shown, drops)
    chains = Counter(tuple(_goal_key(intent) for intent in session.chain) for session in sessions)
    units: list[Unit] = []
    for session in sessions:
        if chains[tuple(_goal_key(intent) for intent in session.chain)] >= MIN_REPEATED_MCP_CHAINS:
            drops[Drop.MCP_REPEATED_CHAIN] += 1
            continue
        units.append(Unit(at=session.at, text=_mcp_line(session, limits)))
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
    mcp: Iterable[McpItem] = (),
) -> RenderedInput | None:
    """The rendered input of one (project, person) pair, or None when nothing survives the filters.

    Order: the named filters, then the burst cap, then the recency-weighted sample, then the hard
    budget, so the sample is drawn from clean units only. `parents` groups activity lines under the
    objects that hold them. The views section shows its lines grouped by type after the budget,
    because the budget drops the oldest unit of a section first. `mcp` holds the calls of the
    person's agent from the MCP intent buffer, and gets its own section after the activity."""
    drops: Counter[str] = Counter()
    activity = list(activity)
    views = list(views)
    task_pool = burst_cap(dedupe_latest(task_units(tasks, drops, limits), drops), drops, limits.max_units_per_day)
    capped_before = drops[Drop.SAMPLE_CAP] + drops[Drop.BURST_CAP]
    activity_lines = activity_units(activity, drops, parents, limits)
    # Lines that `activity_units` dropped for its line cap or its per-day cap.
    activity_pool = len(activity_lines) + drops[Drop.SAMPLE_CAP] + drops[Drop.BURST_CAP] - capped_before
    view_lines = view_units(views, activity, drops, limits)
    pages = page_products(views, drops)
    mcp_pool = burst_cap(
        dedupe_latest(mcp_units(mcp, activity_lines, drops, limits), drops), drops, limits.max_units_per_day
    )
    if not task_pool and not activity_lines and not view_lines and not mcp_pool and not pages:
        return None
    chosen_tasks = sample_units(task_pool, limit=limits.task_lines, as_of=as_of, seed=seed)
    drops[Drop.SAMPLE_CAP] += len(task_pool) - len(chosen_tasks)
    chosen_mcp = sample_units(mcp_pool, limit=limits.mcp_lines, as_of=as_of, seed=seed)
    drops[Drop.SAMPLE_CAP] += len(mcp_pool) - len(chosen_mcp)
    sections = [
        (TASKS_HEADER, chosen_tasks),
        (ACTIVITY_HEADER, activity_lines),
        (MCP_HEADER, chosen_mcp),
        (VIEWS_HEADER, view_lines),
    ]
    enforce_budget(sections, drops, limits.sections_max_chars)
    sections[3] = (VIEWS_HEADER, sorted(sections[3][1], key=lambda unit: unit.text))
    rendered = [_section(header, units) for header, units in sections]
    text = "\n\n".join(part for part in rendered if part)
    return RenderedInput(
        text=text,
        n_tasks=len(sections[0][1]),
        n_activity_lines=len(sections[1][1]),
        n_view_lines=len(sections[3][1]),
        task_chars=len(rendered[0]),
        activity_chars=len(rendered[1]),
        view_chars=len(rendered[3]),
        input_chars=len(text),
        input_tokens_estimate=estimate_tokens(len(text)),
        drops={str(reason): count for reason, count in sorted(drops.items()) if count},
        task_pool=len(task_pool),
        activity_pool=activity_pool,
        intent_lines=sum(1 for unit in sections[1][1] if unit.intent_chars),
        intent_chars=sum(unit.intent_chars for unit in sections[1][1]),
        n_mcp_lines=len(sections[2][1]),
        mcp_chars=len(rendered[2]),
        mcp_pool=len(mcp_pool),
        n_page_units=len(pages),
    )
