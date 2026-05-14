from dataclasses import dataclass
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
class MCPSession:
    session_id: str
    event_count: int
    first_seen: datetime
    last_seen: datetime
    distinct_id_count: int
    tools_used: list[str]
    mcp_client_name: str
    distinct_id: str
    person_email: str
    person_name: str
    intent: str


@dataclass(frozen=True)
class MCPToolCall:
    event_id: str
    timestamp: datetime
    tool_name: str
    intent: str
    is_error: bool
    error_message: str
    duration_ms: int | None
