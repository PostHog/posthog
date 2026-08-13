from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .enums import SubmissionKind


class IntentGenerationUnavailable(RuntimeError):
    """Raised when session-intent generation can't complete (LLM unconfigured or request failed).

    Part of the facade contract: callers (e.g. the presentation layer) catch this to surface a
    clean error instead of a 500.
    """


@dataclass(frozen=True)
class Submission:
    id: UUID
    kind: SubmissionKind
    goal: str
    summary: str
    category: str
    blocked: bool | None
    attempted_tool: str
    mcp_client_name: str
    mcp_client_version: str
    mcp_protocol_version: str
    mcp_transport: str
    mcp_session_id: str
    mcp_trace_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SubmissionContext:
    attempted_tool: str = ""
    mcp_client_name: str = ""
    mcp_client_version: str = ""
    mcp_protocol_version: str = ""
    mcp_transport: str = ""
    mcp_session_id: str = ""
    mcp_trace_id: str = ""


@dataclass(frozen=True)
class CreateFeedbackSubmission:
    goal: str
    feedback: str
    category: str = "other"
    context: SubmissionContext = SubmissionContext()


@dataclass(frozen=True)
class CreateMissingCapabilitySubmission:
    goal: str
    missing_capability: str
    blocked: bool = True
    context: SubmissionContext = SubmissionContext()


@dataclass(frozen=True)
class MCPSession:
    session_id: str
    tool_calls: int
    session_start: datetime
    session_end: datetime
    distinct_id_count: int
    tools_used: list[str]
    mcp_client_name: str
    distinct_id: str
    person_email: str
    person_name: str
    intent: str


@dataclass(frozen=True)
class MCPSessionsPage:
    results: list[MCPSession]
    has_next: bool


@dataclass(frozen=True)
class MCPToolCall:
    event_id: str
    timestamp: datetime
    tool_name: str
    intent: str
    is_error: bool
    error_message: str
    duration_ms: int | None


@dataclass(frozen=True)
class MCPToolCallsPage:
    results: list[MCPToolCall]
    has_next: bool


@dataclass(frozen=True)
class IntentClusterToolEntry:
    tool: str
    count: int
    pct: float
    errors: int
    error_rate_pct: float


@dataclass(frozen=True)
class IntentClusterJourneyPath:
    steps: list[str | None]
    outcome: str
    count: int


@dataclass(frozen=True)
class IntentClusterJourney:
    paths: list[IntentClusterJourneyPath]
    total_sessions: int
    leak: IntentClusterJourneyPath | None


@dataclass(frozen=True)
class ClusterSwitch:
    from_tool: str
    to_tool: str
    count: int


@dataclass(frozen=True)
class ClusterSelfRetry:
    tool: str
    count: int


@dataclass(frozen=True)
class IntentCluster:
    id: int
    label: str
    intent_count: int
    session_count: int
    call_count: int
    error_count: int
    error_rate_pct: float
    routing_entropy: float
    tool_distribution: list[IntentClusterToolEntry]
    sample_intents: list[str]
    journey: IntentClusterJourney | None = None
    switches: list[ClusterSwitch] = field(default_factory=list)
    self_retries: list[ClusterSelfRetry] = field(default_factory=list)


@dataclass(frozen=True)
class ToolPivotCompetitor:
    tool: str
    pct: float


@dataclass(frozen=True)
class ToolPivotClusterEntry:
    """One tool's slice of one cluster. Deliberately carries no per-cluster
    constants — the cluster's label, totals, and entropy are joined on
    ``cluster_id`` so the blob doesn't repeat them once per tool."""

    cluster_id: int
    calls: int
    capture_pct: float
    rank: int
    description_fit: float | None = None
    top_competitor: ToolPivotCompetitor | None = None


@dataclass(frozen=True)
class ToolPivot:
    tool: str
    call_count: int
    error_count: int
    session_count: int
    contested_score: float | None
    advertised_sessions: int
    called_when_advertised: int
    discovery_rate_pct: float | None
    description: str | None
    n_clusters_served: int = 0
    clusters: list[ToolPivotClusterEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ToolOverlap:
    tool_a: str
    tool_b: str
    contested_calls: int
    sessions_with_both: int
    sessions_with_either: int
    top_cluster_id: int


@dataclass(frozen=True)
class IntentClusterSnapshotMeta:
    distance_threshold: float
    embedding_model: str
    n_intents: int
    n_clusters: int
    # v2 (per-call corpus) coverage fields; None on snapshots computed before v2.
    corpus: str | None = None
    sampled_sessions: int | None = None
    window_sessions: int | None = None
    session_coverage_pct: float | None = None
    intent_coverage_pct: float | None = None
    imputed_call_pct: float | None = None
    unattributed_call_pct: float | None = None
    corpus_call_coverage_pct: float | None = None
    advertisement_coverage_pct: float | None = None
    n_tools: int | None = None
    dropped_tools: int | None = None
    dropped_overlap_pairs: int | None = None
    description_coverage_pct: float | None = None


@dataclass(frozen=True)
class IntentClusterSnapshot:
    status: str
    error_message: str
    last_computed_at: datetime | None
    last_computed_by_email: str
    clusters: list[IntentCluster] = field(default_factory=list)
    computed_with: IntentClusterSnapshotMeta | None = None
    tools: list[ToolPivot] = field(default_factory=list)
    tool_overlaps: list[ToolOverlap] = field(default_factory=list)


@dataclass(frozen=True)
class IntentTheme:
    """One semantic grouping of agent intents in the project digest.

    ``name`` and ``description`` come from the LLM; ``intent_count``, ``example_intent``, and
    ``tools`` are resolved from the intents it grouped, so no figure on the card is invented.
    """

    name: str
    description: str
    intent_count: int
    example_intent: str
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntentDigest:
    """Project-level LLM digest of what agents are trying to do with the MCP server."""

    # Null when the project has no recorded intents to summarise yet.
    digest: str | None
    intent_count: int
    themes: list[IntentTheme] = field(default_factory=list)


@dataclass(frozen=True)
class ActivityStats:
    """Aggregate counters over the activity window, for the dashboard's activity stage."""

    total_calls: int
    distinct_tools: int
    distinct_sessions: int
    distinct_clients: int
    calls_with_intent: int
    error_calls: int
    missing_capability_reports: int


@dataclass(frozen=True)
class ActivityToolRow:
    tool: str
    calls: int
    errors: int


@dataclass(frozen=True)
class ActivityClientRow:
    client: str
    calls: int


@dataclass(frozen=True)
class ActivityRecentCall:
    timestamp: datetime
    tool: str
    intent: str | None
    is_error: bool
    # Human-readable message extracted from the tool's error response, when the call failed.
    error_message: str | None
    duration_ms: float | None
    client_name: str | None


@dataclass(frozen=True)
class ActivityOverview:
    """Everything the activity view renders, computed server-side in one request."""

    stats: ActivityStats
    top_tools: list[ActivityToolRow] = field(default_factory=list)
    clients: list[ActivityClientRow] = field(default_factory=list)
    recent_calls: list[ActivityRecentCall] = field(default_factory=list)
