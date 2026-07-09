# Source of truth for the signal payload taxonomy — the shared contract between backend emitters,
# the facade's validation, and the inbox cards. The frontend TypeScript equivalents are generated
# from these models: the extras are declared on the `signals`-endpoint serializer (see
# `SignalNodeSerializer` in `serializers.py`), so they flow through the standard OpenAPI/Orval pipeline.

import enum
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

from products.signals.backend.enums import ReportPriority, SignalSourceProduct, SignalSourceType


class ContractModel(BaseModel):
    # Emitted payloads are validated against these models at the emit boundary; unknown fields are
    # rejected rather than silently written to signal metadata (parity with the generated schema.py
    # models these replaced, which all carried extra="forbid").
    model_config = ConfigDict(extra="forbid")


class SignalRemediation(ContractModel):
    human: str
    agent: str
    priority: ReportPriority | None = None


class SignalExtraBase(ContractModel):
    pass


class SignalInputBase(ContractModel):
    source_id: str
    description: str
    weight: float
    remediation: SignalRemediation | None = None


# ── Session replay ──────────────────────────────────────────────────────────────


class SessionProblemEventEntry(ContractModel):
    event: str
    timestamp: str
    current_url: str | None = None
    event_type: str | None = None
    interaction_text: str | None = None


class SessionProblemSignalExtra(SignalExtraBase):
    session_id: str
    segment_title: str
    start_time: str
    end_time: str
    problem_type: Literal["confusion", "abandonment", "blocking_exception", "non_blocking_exception", "failure"]
    distinct_id: str
    session_start_time: str | None = None
    session_end_time: str | None = None
    session_duration: float | None = None
    session_active_seconds: float | None = None
    exported_asset_id: int | None = None
    event_history: list[SessionProblemEventEntry] | None = None


class SessionProblemSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SESSION_PROBLEM]
    source_product: Literal[SignalSourceProduct.SESSION_REPLAY]
    extra: SessionProblemSignalExtra


# ── LLM analytics ───────────────────────────────────────────────────────────────


class LlmEvalSignalExtra(SignalExtraBase):
    evaluation_id: str
    target_event_id: str | None = None
    target_event_type: str | None = None
    trace_id: str
    model: str | None = None
    provider: str | None = None


class LlmEvaluationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.EVALUATION]
    source_product: Literal[SignalSourceProduct.LLM_ANALYTICS]
    extra: LlmEvalSignalExtra


class LlmEvalReportSignalExtra(SignalExtraBase):
    evaluation_id: str
    evaluation_name: str
    evaluation_description: str
    report_id: str
    report_run_id: str
    period_start: str
    period_end: str


class LlmEvaluationReportSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.EVALUATION_REPORT]
    source_product: Literal[SignalSourceProduct.LLM_ANALYTICS]
    extra: LlmEvalReportSignalExtra


# ── Zendesk ─────────────────────────────────────────────────────────────────────


class ZendeskTicketSignalExtra(SignalExtraBase):
    url: str
    type: str | None
    tags: list[str]
    created_at: str
    priority: str | None
    status: str


class ZendeskTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.ZENDESK]
    extra: ZendeskTicketSignalExtra


# ── GitHub ──────────────────────────────────────────────────────────────────────


class GithubIssueSignalExtra(SignalExtraBase):
    html_url: str
    number: int
    labels: list[str]
    created_at: str
    updated_at: str
    locked: bool
    state: str


class GithubIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.GITHUB]
    extra: GithubIssueSignalExtra


# ── Linear ──────────────────────────────────────────────────────────────────────


class LinearIssueSignalExtra(SignalExtraBase):
    url: str
    identifier: str
    number: int
    priority: int
    priority_label: str
    labels: list[str]
    state_name: str | None
    state_type: str | None
    team_name: str | None
    created_at: str
    updated_at: str


class LinearIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.LINEAR]
    extra: LinearIssueSignalExtra


# ── Jira ────────────────────────────────────────────────────────────────────────


class JiraIssueSignalExtra(SignalExtraBase):
    key: str
    url: str | None
    status: str | None
    priority: str | None
    assignee: str | None
    labels: list[str]
    created: str | None
    updated: str | None


class JiraIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.JIRA]
    extra: JiraIssueSignalExtra


# ── Conversations ───────────────────────────────────────────────────────────────


class ConversationsTicketSignalExtra(SignalExtraBase):
    ticket_number: int
    channel_source: str
    channel_detail: str | None
    status: str
    priority: str | None
    created_at: str
    email_subject: str | None


class ConversationsTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.CONVERSATIONS]
    extra: ConversationsTicketSignalExtra


# ── Error tracking ──────────────────────────────────────────────────────────────


class ErrorTrackingSignalExtra(SignalExtraBase):
    fingerprint: str


class ErrorTrackingSignalInput(SignalInputBase):
    source_type: Literal[
        SignalSourceType.ISSUE_CREATED, SignalSourceType.ISSUE_REOPENED, SignalSourceType.ISSUE_SPIKING
    ]
    source_product: Literal[SignalSourceProduct.ERROR_TRACKING]
    extra: ErrorTrackingSignalExtra


# ── pganalyze ───────────────────────────────────────────────────────────────────


class PgAnalyzeIssueReference(ContractModel):
    # pganalyze reference objects omit nullable keys entirely (e.g. index/table refs
    # carry no queryText), so these need defaults to keep such refs valid.
    kind: str | None = None
    name: str | None = None
    url: str | None = None
    queryText: str | None = None


class PgAnalyzeIssueSignalExtra(SignalExtraBase):
    severity: str | None
    references: list[PgAnalyzeIssueReference]
    database_id: str | None
    server_human_id: str | None
    server_name: str | None
    synced_at: str


class PgAnalyzeIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.PGANALYZE]
    extra: PgAnalyzeIssueSignalExtra


# ── Endpoints ───────────────────────────────────────────────────────────────────


class EndpointExecutionFailedSignalExtra(SignalExtraBase):
    endpoint_name: str
    endpoint_version: int | None
    materialized: bool
    saved_query_id: str | None
    error_class: str
    error_message: str


class EndpointExecutionFailedSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ENDPOINT_EXECUTION_FAILED]
    source_product: Literal[SignalSourceProduct.ENDPOINTS]
    extra: EndpointExecutionFailedSignalExtra


class EndpointBreakdownLimitExceededSignalExtra(SignalExtraBase):
    endpoint_name: str
    breakdown_limit: int


class EndpointBreakdownLimitExceededSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ENDPOINT_BREAKDOWN_LIMIT_EXCEEDED]
    source_product: Literal[SignalSourceProduct.ENDPOINTS]
    extra: EndpointBreakdownLimitExceededSignalExtra


# ── Signals scout ───────────────────────────────────────────────────────────────


class SignalsScoutEvidenceEntry(ContractModel):
    source_product: str
    entity_id: str | None = None
    summary: str


class SignalsScoutTimeRange(ContractModel):
    date_from: str
    date_to: str


class SignalsScoutSignalExtra(SignalExtraBase):
    scout_run_id: str
    task_run_id: str
    task_id: str | None = None
    finding_id: str
    skill_name: str
    skill_version: int
    confidence: float
    severity: ReportPriority | None = None
    hypothesis: str | None = None
    evidence: list[SignalsScoutEvidenceEntry]
    dedupe_keys: list[str] | None = None
    tags: list[str] | None = None
    time_range: SignalsScoutTimeRange | None = None
    mcp_trace_id: str | None = None


class SignalsScoutSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.CROSS_SOURCE_ISSUE]
    source_product: Literal[SignalSourceProduct.SIGNALS_SCOUT]
    extra: SignalsScoutSignalExtra


# ── Logs ────────────────────────────────────────────────────────────────────────


class LogsAlertStateChangeSignalExtra(SignalExtraBase):
    alert_id: str
    alert_name: str
    action: Literal["firing", "broken"]
    threshold_count: int
    threshold_operator: Literal["above", "below"]
    window_minutes: int
    result_count: int | None
    consecutive_failures: int
    filters: dict[str, object]
    url: str


class LogsAlertStateChangeSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ALERT_STATE_CHANGE]
    source_product: Literal[SignalSourceProduct.LOGS]
    extra: LogsAlertStateChangeSignalExtra


# ── Replay vision ───────────────────────────────────────────────────────────────


class ReplayVisionScannerFindingSignalExtra(SignalExtraBase):
    scanner_id: str
    scanner_name: str
    scanner_type: str
    observation_id: str
    session_id: str
    confidence: float
    problem_type: str
    start_time: float
    end_time: float
    url: str
    exported_asset_id: int
    distinct_id: str | None = None
    recording_start_time: str | None = None
    recording_end_time: str | None = None
    recording_duration: float | None = None
    recording_active_seconds: float | None = None


class ReplayVisionScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.REPLAY_VISION]
    extra: ReplayVisionScannerFindingSignalExtra


# ── Health checks ───────────────────────────────────────────────────────────────

HealthCheckSeverity = Literal["critical", "warning", "info"]


class HealthCheckSignalExtra(SignalExtraBase):
    kind: str
    severity: HealthCheckSeverity
    issue_id: str
    title: str
    summary: str
    link: str
    url: str
    payload: dict[str, object]


class HealthCheckSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.HEALTH_ISSUE]
    source_product: Literal[SignalSourceProduct.HEALTH_CHECKS]
    extra: HealthCheckSignalExtra


# ── Report reviewer types ───────────────────────────────────────────────────────


class RelevantCommit(ContractModel):
    sha: str
    url: str
    reason: str


class SignalReviewerUserInfo(ContractModel):
    id: int
    uuid: str
    first_name: str
    last_name: str
    email: str


class EnrichedReviewer(ContractModel):
    github_login: str
    github_name: str | None
    relevant_commits: list[RelevantCommit]
    user: SignalReviewerUserInfo | None


# ── Union over all signal variants ──────────────────────────────────────────────
# Discrimination is by the composite (source_product, source_type) pair, resolved via
# SIGNAL_VARIANT_LOOKUP below — a single-field pydantic discriminator can't express it
# because llm_analytics/error_tracking map several (product, type) pairs to one variant and
# github/linear/pganalyze share source_type="issue".

SignalInput = Annotated[
    SessionProblemSignalInput
    | LlmEvaluationSignalInput
    | LlmEvaluationReportSignalInput
    | ZendeskTicketSignalInput
    | GithubIssueSignalInput
    | LinearIssueSignalInput
    | JiraIssueSignalInput
    | ConversationsTicketSignalInput
    | ErrorTrackingSignalInput
    | EndpointExecutionFailedSignalInput
    | EndpointBreakdownLimitExceededSignalInput
    | PgAnalyzeIssueSignalInput
    | SignalsScoutSignalInput
    | LogsAlertStateChangeSignalInput
    | HealthCheckSignalInput
    | ReplayVisionScannerFindingSignalInput,
    Field(union_mode="left_to_right"),
]

SIGNAL_INPUT_VARIANTS: tuple[type[SignalInputBase], ...] = (
    SessionProblemSignalInput,
    LlmEvaluationSignalInput,
    LlmEvaluationReportSignalInput,
    ZendeskTicketSignalInput,
    GithubIssueSignalInput,
    LinearIssueSignalInput,
    JiraIssueSignalInput,
    ConversationsTicketSignalInput,
    ErrorTrackingSignalInput,
    EndpointExecutionFailedSignalInput,
    EndpointBreakdownLimitExceededSignalInput,
    PgAnalyzeIssueSignalInput,
    SignalsScoutSignalInput,
    LogsAlertStateChangeSignalInput,
    HealthCheckSignalInput,
    ReplayVisionScannerFindingSignalInput,
)


def _literal_values(field: FieldInfo) -> tuple[str, ...]:
    """The accepted string values for a variant's `source_product` / `source_type` Literal field."""
    args = get_args(field.annotation)
    return tuple(arg.value if isinstance(arg, enum.Enum) else arg for arg in args)


# (source_product, source_type) -> variant model. The pair is the discriminator: several products
# share a source_type ("issue", "ticket") and error_tracking maps three types to one variant, so a
# single-field discriminator can't express it. Built once at import.
def _build_variant_lookup() -> dict[tuple[str, str], type[SignalInputBase]]:
    lookup: dict[tuple[str, str], type[SignalInputBase]] = {}
    for variant in SIGNAL_INPUT_VARIANTS:
        for product in _literal_values(variant.model_fields["source_product"]):
            for source_type in _literal_values(variant.model_fields["source_type"]):
                lookup[(product, source_type)] = variant
    return lookup


SIGNAL_VARIANT_LOOKUP: dict[tuple[str, str], type[SignalInputBase]] = _build_variant_lookup()
