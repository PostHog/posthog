"""
Contract types for githog.

Stable, framework-free frozen dataclasses that define what this
product exposes to the rest of the codebase.

Characteristics:
- No Django imports
- Immutable (frozen=True)
- Used by facade as inputs/outputs

Do NOT depend on Django models, DRF serializers, or request objects.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FlagReference:
    """A feature flag key found in a diff, with where it was referenced."""

    key: str
    file_paths: tuple[str, ...]
    occurrences: int


@dataclass(frozen=True)
class FlagReach:
    """Empirical reach of a single flag, measured from $feature_flag_called events."""

    key: str
    users_affected: int
    sessions_affected: int
    call_count: int
    variants: tuple["VariantReach", ...] = ()
    # True iff the flag key appears in $feature_flag_called events in the window.
    # When False, the flag exists in code but has no recorded evaluations — reach
    # is "unknown," not "zero" (likely a brand-new flag).
    has_data: bool = True
    # True when the evaluation pattern looks server-side — i.e. a single (or
    # very few) distinct_id evaluated the flag many times. In that case
    # ``users_affected`` is the service identity count, not real humans —
    # ``call_count`` is the meaningful "reach" number.
    is_server_side: bool = False


@dataclass(frozen=True)
class VariantReach:
    """Per-variant reach for multivariate flags."""

    variant: str
    users_affected: int


@dataclass(frozen=True)
class EventReference:
    """An event name found being captured in a diff."""

    name: str
    file_paths: tuple[str, ...]
    occurrences: int


@dataclass(frozen=True)
class EventReach:
    """Empirical reach of a single event over the lookback window."""

    name: str
    users_affected: int
    sessions_affected: int
    call_count: int
    # False when no rows came back — the event name exists in code but has not
    # fired (recently or ever). Reach is "unknown / no data," not "zero."
    has_data: bool = True
    # See FlagReach.is_server_side — same regime detection applied to event
    # capture, which can also be a server-side firehose under one service id.
    is_server_side: bool = False


@dataclass(frozen=True)
class DashboardReference:
    """A saved insight or dashboard that references at least one flag/event from the PR.

    ``kind`` is "insight" or "dashboard". For insights, ``short_id`` is the
    human-friendly ID used in URLs; for dashboards it's None.
    """

    kind: str
    id: int
    name: str
    short_id: str | None
    matched_keys: tuple[str, ...]


@dataclass(frozen=True)
class RelatedSignal:
    """A flag key or event name that shares filename tokens with this PR's files.

    Not literally referenced in the diff — surfaced as a "you may also care about
    this" suggestion. Reach numbers are still real (measured the same way as
    confirmed references), so reviewers get something to decide on.
    """

    kind: str  # "flag" | "event"
    key: str
    matched_tokens: tuple[str, ...]
    users_affected: int
    sessions_affected: int
    call_count: int
    is_server_side: bool
    has_data: bool


@dataclass(frozen=True)
class LLMPick:
    """One signal the LLM judges most important for this PR."""

    kind: str  # "flag" | "event" | "dashboard" | "issue"
    key: str
    reason: str


@dataclass(frozen=True)
class AffectedEstimate:
    """The model's grounded estimate of how many users this PR affects.

    The headline is the glanceable answer ("Most users", "~14k users",
    "iOS users with active flights"). The numeric range backs it up so
    reviewers can sanity-check; ``share_*`` expresses the same as a
    fraction of the team's active base when that's the more legible
    framing. ``confidence`` is the model's own self-rating. ``unit``
    distinguishes humans from server-side firehoses.
    """

    headline: str
    unit: str  # "users" | "events" | "requests" | "unknown"
    lower: int | None
    upper: int | None
    share_lower: float | None  # 0.0 - 1.0
    share_upper: float | None
    confidence: str  # "high" | "medium" | "low"
    rationale: str


@dataclass(frozen=True)
class LLMAnalysis:
    """LLM-driven synthesis of the PR's blast radius.

    Produced by an orchestrator that has tool access to the team's flag /
    event catalog and reach queries — so the numbers it cites come from
    real PostHog data, not the model's imagination. When the LLM call
    fails or no API key is configured, this is None on the report.
    """

    headline: str
    summary: str
    top_picks: tuple[LLMPick, ...]
    # Glanceable answer to "how many users will this affect" — separate from
    # the wall-of-text summary so the UI can render it loudly.
    affected: AffectedEstimate | None = None
    # Short descriptors of *who* is affected: "iOS users", "users on the paid
    # plan", "anyone with an active flight." 1-4 phrases.
    audience: tuple[str, ...] = field(default_factory=tuple)
    # Free-form notes from the model (e.g. "no recent activity found for any
    # surface — likely a green-field area"). Surfaced so reviewers can see
    # the model's caveats without us interpreting them.
    caveats: tuple[str, ...] = field(default_factory=tuple)
    # Bookkeeping for the demo: how many tool round-trips the model used,
    # so we can spot runaway loops or "didn't try hard enough" cases.
    tool_calls_used: int = 0


@dataclass(frozen=True)
class WebPathReach:
    """Pageview reach for a URL path implicated by this PR.

    Paths come from two sources, distinguished by ``matched_from``:
      - ``"diff_literal"``: a string literal like ``"/pricing"`` appeared in
        added/context lines of the diff.
      - ``"llm_tool"``: the LLM identified the path from reading the diff
        (framework-aware: Next.js routing, Express routes, etc.) and pulled
        reach via a tool call.

    Counts come from ``$pageview`` events grouped by ``properties.$pathname``.
    """

    path: str
    pageviews: int
    unique_visitors: int
    sessions: int
    has_data: bool
    matched_from: str


@dataclass(frozen=True)
class IssueReference:
    """An Error Tracking issue whose recent events implicate code in this PR.

    Match driver is in ``matched_terms`` — either a touched file path that
    appears in the issue's stack frames, or a flag key / event name that
    appears in the exception payload.
    """

    id: str
    name: str
    status: str
    occurrences: int
    users_affected: int
    sample_message: str
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class PRImpactRequest:
    """Input for computing PR impact.

    Caller supplies the diff text directly — this keeps the facade
    decoupled from any specific GitHub fetching layer. A thin wrapper
    elsewhere can pull diffs from gh/git and feed them in.
    """

    diff_text: str
    lookback_days: int = 30


@dataclass(frozen=True)
class PRImpactReport:
    """Result of impact analysis."""

    flag_references: tuple[FlagReference, ...]
    per_flag_reach: tuple[FlagReach, ...]
    # Users who had EVERY referenced flag evaluated truthy in the window.
    # This is the empirical intersection — the correct answer to
    # "how many users will see this code path," modulo flags outside the diff.
    intersection_users: int
    intersection_sessions: int
    lookback_days: int
    event_references: tuple[EventReference, ...] = field(default_factory=tuple)
    per_event_reach: tuple[EventReach, ...] = field(default_factory=tuple)
    dashboard_references: tuple[DashboardReference, ...] = field(default_factory=tuple)
    issue_references: tuple[IssueReference, ...] = field(default_factory=tuple)
    related_signals: tuple[RelatedSignal, ...] = field(default_factory=tuple)
    web_paths: tuple[WebPathReach, ...] = field(default_factory=tuple)
    # Surfaced so the empty state can say *what* was searched, not just "no matches."
    changed_files: tuple[str, ...] = field(default_factory=tuple)
    known_flag_count: int = 0
    known_event_count: int = 0
    llm_analysis: LLMAnalysis | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
