from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from .enums import SubmissionKind


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
class IntentClusterSampleIntent:
    intent: str
    total_calls: int
    error_rate: float
    empty_rate: float


@dataclass(frozen=True)
class IntentCluster:
    cluster_id: int
    title: str
    description: str
    gap_score: float
    size: int
    aggregate_error_rate: float
    aggregate_empty_rate: float
    avg_distinct_tools_attempted: float
    sample_intents: list[IntentClusterSampleIntent]


@dataclass(frozen=True)
class LLMStatedGap:
    probe_phrase: str
    matched_text: str
    distance: float
    document_id: str
    timestamp: datetime | None


@dataclass(frozen=True)
class MissingToolsCandidates:
    clustering_run_id: str
    window_start: str
    window_end: str
    intent_clusters: list[IntentCluster] = field(default_factory=list)
    llm_stated_gaps: list[LLMStatedGap] = field(default_factory=list)
