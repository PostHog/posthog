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


@dataclass(frozen=True)
class IntentClusterSnapshotMeta:
    distance_threshold: float
    embedding_model: str
    n_intents: int
    n_clusters: int


@dataclass(frozen=True)
class IntentClusterSnapshot:
    status: str
    error_message: str
    last_computed_at: datetime | None
    last_computed_by_email: str
    clusters: list[IntentCluster] = field(default_factory=list)
    computed_with: IntentClusterSnapshotMeta | None = None
