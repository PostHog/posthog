# Source of truth for the signal payload taxonomy — the shared contract between backend emitters,
# the facade's validation, and the inbox cards. The frontend TypeScript equivalents are generated
# from these models: the extras are declared on the `signals`-endpoint serializer (see
# `SignalNodeSerializer` in `serializers.py`), so they flow through the standard OpenAPI/Orval pipeline.

import enum
from collections.abc import Mapping
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

from products.signals.backend.enums import ReportPriority, SignalSourceProduct, SignalSourceType

# ── Source-config steering keys ─────────────────────────────────────────────────
# Public keys of `SignalSourceConfig.config` shared by every emission source. Defined here
# (not in `emission/`) so the serializer can validate them without importing the emission
# package, whose __init__ eagerly registers every emitter and must stay off the web path.

STEERING_KEY = "steering"
DEFAULT_NOT_ACTIONABLE_KEY = "default_not_actionable"
# Server-side cap on steering text. The serializer rejects longer input; reads truncate
# defensively so a row written by another path cannot bloat every gate prompt.
STEERING_MAX_LENGTH = 2000

# ── Scope allowlists ────────────────────────────────────────────────────────────
# Per-source `SignalSourceConfig.config` key holding the allowlist of scope ids emission narrows to.
# Kept out of `emission/` for the same reason as the steering keys above.
SCOPE_CONFIG_KEYS: Mapping[tuple[str, str], str] = {
    (SignalSourceProduct.LINEAR, SignalSourceType.ISSUE): "linear_team_ids",
}
SCOPE_IDS_MAX_COUNT = 100
# Both caps keep a row written outside the API from bloating the emission query past ClickHouse's size limit.
SCOPE_ID_MAX_LENGTH = 255


def scope_ids_problem(value: object) -> str | None:
    """Why `value` is not a valid scope allowlist, or None when it is. The API rejects the value
    with this message; the fetcher falls back to reading everything, so a malformed row never
    applies part of a list."""
    if not isinstance(value, list) or not all(isinstance(scope_id, str) and scope_id.strip() for scope_id in value):
        return "must be a list of non-empty strings"
    if len(value) > SCOPE_IDS_MAX_COUNT:
        return f"must have at most {SCOPE_IDS_MAX_COUNT} entries"
    if any(len(scope_id.strip()) > SCOPE_ID_MAX_LENGTH for scope_id in value):
        return f"entries must be at most {SCOPE_ID_MAX_LENGTH} characters"
    return None


# The sources that emit straight through `emit_signal` and still honor steering, via the gate in
# `emission/direct_gate.py`. Every other direct source skips the gate, so writing steering onto its
# row would store text nothing reads. The roster's `steerable` flags in `agentRosterMeta.ts` mirror
# this set, and only these pairs may be offered the steering form.
DIRECT_STEERABLE_SOURCES: frozenset[tuple[str, str]] = frozenset(
    {
        (SignalSourceProduct.ERROR_TRACKING, SignalSourceType.ISSUE_CREATED),
        (SignalSourceProduct.ERROR_TRACKING, SignalSourceType.ISSUE_REOPENED),
        (SignalSourceProduct.ERROR_TRACKING, SignalSourceType.ISSUE_SPIKING),
        (SignalSourceProduct.HEALTH_CHECKS, SignalSourceType.HEALTH_ISSUE),
    }
)


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


# Read-only: no emitter writes `llm_analytics/evaluation` signals any more (only whole eval reports
# do), but signals ingested while that path existed keep this payload shape, and the inbox card that
# renders them is generated from this model.
class LlmEvalSignalExtra(SignalExtraBase):
    evaluation_id: str
    target_event_id: str | None = None
    target_event_type: str | None = None
    trace_id: str
    model: str | None = None
    provider: str | None = None


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
    # Defaulted, unlike the fields above: payloads emitted before these columns existed carry
    # neither key, and an author is context for triage rather than something a signal needs.
    author_login: str | None = None
    # GitHub's own enum — OWNER, MEMBER, COLLABORATOR, CONTRIBUTOR, FIRST_TIME_CONTRIBUTOR,
    # FIRST_TIMER, MANNEQUIN, NONE. Kept as a plain string so a value GitHub adds later widens the
    # taxonomy instead of failing validation and dropping the signal.
    author_association: str | None = None


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


class ConversationsTicketImage(ContractModel):
    url: str
    author: str


class ConversationsTicketSignalExtra(SignalExtraBase):
    ticket_number: int
    channel_source: str
    channel_detail: str | None
    status: str
    priority: str | None
    created_at: str
    email_subject: str | None
    # Publicly fetchable media URLs pasted into the thread, so the research agent can inspect
    # screenshots directly. Absent (rather than empty) when the thread has no attachments.
    images: list[ConversationsTicketImage] | None = None


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


# ── Report checks ──────────────────────────────────────────────────────────────


class CheckFailedSignalExtra(SignalExtraBase):
    check_id: str
    report_id: str
    check_title: str
    explanation: str
    observed_value: float | None = None
    baseline_value: float | None = None
    threshold: str | None = None


class CheckFailedSignalInput(SignalInputBase):
    """A deterministic check that breached after its report was resolved.

    The inbox emitting to itself. An `agent` check has a scout that can author a fresh report; a
    `metric_threshold` check has nobody, so the verdict becomes a signal and the pipeline treats the
    relapse the way it treats any other recurrence on a resolved report.
    """

    source_type: Literal[SignalSourceType.CHECK_FAILED]
    source_product: Literal[SignalSourceProduct.SIGNALS_CHECK]
    extra: CheckFailedSignalExtra


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
    # The group a grouped alert fired for, by column. Absent for an ungrouped alert.
    group_labels: dict[str, str] | None = None


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


# ── Product analytics ───────────────────────────────────────────────────────────


class AnalyticsAnomalyInvestigationSignalExtra(SignalExtraBase):
    alert_id: str
    alert_name: str
    alert_check_id: str
    insight_id: str
    detector_type: str
    verdict: Literal["true_positive", "false_positive", "inconclusive"]
    url: str
    insight_name: str | None = None
    insight_short_id: str | None = None
    triggered_dates: list[str] | None = None
    notebook_short_id: str | None = None


class AnalyticsAnomalyInvestigationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ANOMALY_INVESTIGATION]
    source_product: Literal[SignalSourceProduct.ANALYTICS]
    extra: AnalyticsAnomalyInvestigationSignalExtra


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


# ── Engineering analytics ───────────────────────────────────────────────────────
# CI signals; detection lives in products/engineering_analytics/backend/logic/signals.


class EngineeringAnalyticsCIFlakyCheckSignalExtra(SignalExtraBase):
    """One immutable flaky observation: failed then passed on a later attempt of the same run,
    so only non-determinism can explain the flip."""

    repo_owner: str
    repo_name: str
    workflow_name: str
    job_name: str
    run_id: int
    head_sha: str
    failed_attempt: int
    passed_attempt: int
    # Runs this job flapped on within the window.
    flaky_count: int
    window_days: int


class EngineeringAnalyticsCIFlakyCheckSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.CI_FLAKY_CHECK]
    source_product: Literal[SignalSourceProduct.ENGINEERING_ANALYTICS]
    extra: EngineeringAnalyticsCIFlakyCheckSignalExtra


class EngineeringAnalyticsCIBrokenDefaultBranchSignalExtra(SignalExtraBase):
    repo_owner: str
    repo_name: str
    workflow_name: str
    branch: str
    # Success rate in [0, 1] over runs that reached a verdict (success / failure / timed_out).
    # Cancelled and skipped runs are excluded: they decided nothing, and counting them makes any
    # workflow whose concurrency group cancels superseded trunk runs read as permanently failing.
    conclusive_success_rate: float
    conclusive_run_count: int
    latest_conclusion: str
    window_hours: int


class EngineeringAnalyticsCIBrokenDefaultBranchSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.CI_BROKEN_DEFAULT_BRANCH]
    source_product: Literal[SignalSourceProduct.ENGINEERING_ANALYTICS]
    extra: EngineeringAnalyticsCIBrokenDefaultBranchSignalExtra


class EngineeringAnalyticsCIDurationRegressionSignalExtra(SignalExtraBase):
    repo_owner: str
    repo_name: str
    workflow_name: str
    current_p95_seconds: float
    baseline_p95_seconds: float
    # Fractional increase of current p95 over baseline (0.5 = +50%).
    pct_increase: float
    current_p50_seconds: float
    baseline_p50_seconds: float
    window_days: int


class EngineeringAnalyticsCIDurationRegressionSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.CI_DURATION_REGRESSION]
    source_product: Literal[SignalSourceProduct.ENGINEERING_ANALYTICS]
    extra: EngineeringAnalyticsCIDurationRegressionSignalExtra


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
    # A reviewer is identified by their PostHog user, their GitHub login, or both. `github_login` is
    # null for a reviewer with no linked GitHub account; `user_uuid` is null on entries written
    # before reviewers carried one, where `user` still resolves from the login at read time.
    github_login: str | None
    user_uuid: str | None = None
    github_name: str | None
    relevant_commits: list[RelevantCommit]
    user: SignalReviewerUserInfo | None
    reason: str | None = None
    source_skill: str | None = None
    source_label: str
    explanation: str | None = None


# ── Tier-1 data-warehouse inbox sources ──────────────────────────────────────────


class FreshdeskTicketSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    type: str | None
    tags: list
    created_at: str | None


class FreshdeskTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.FRESHDESK]
    extra: FreshdeskTicketSignalExtra


class FreshserviceTicketSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    type: str | None
    category: str | None
    tags: list
    created_at: str | None


class FreshserviceTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.FRESHSERVICE]
    extra: FreshserviceTicketSignalExtra


class FrontConversationSignalExtra(SignalExtraBase):
    status: str | None
    tags: list
    created_at: str | None


class FrontConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.FRONT]
    extra: FrontConversationSignalExtra


class GorgiasTicketSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    channel: str | None
    tags: list
    created_datetime: str | None


class GorgiasTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.GORGIAS]
    extra: GorgiasTicketSignalExtra


class KustomerConversationSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    tags: list
    created_at: str | None


class KustomerConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.KUSTOMER]
    extra: KustomerConversationSignalExtra


class DixaConversationSignalExtra(SignalExtraBase):
    status: str | None
    channel: str | None
    tags: list
    created_at: str | None


class DixaConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.DIXA]
    extra: DixaConversationSignalExtra


class PlainThreadSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    labels: list
    created_at: str | None


class PlainThreadSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.PLAIN]
    extra: PlainThreadSignalExtra


class GitlabIssueSignalExtra(SignalExtraBase):
    state: str | None
    labels: list
    iid: str | None
    project_id: str | None
    created_at: str | None


class GitlabIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.GITLAB]
    extra: GitlabIssueSignalExtra


class GiteaIssueSignalExtra(SignalExtraBase):
    state: str | None
    labels: list
    html_url: str | None
    number: str | None
    created_at: str | None


class GiteaIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.GITEA]
    extra: GiteaIssueSignalExtra


class ShortcutStorySignalExtra(SignalExtraBase):
    story_type: str | None
    labels: list
    workflow_state_id: str | None
    created_at: str | None


class ShortcutStorySignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.SHORTCUT]
    extra: ShortcutStorySignalExtra


class SentryIssueSignalExtra(SignalExtraBase):
    level: str | None
    status: str | None
    permalink: str | None
    short_id: str | None
    first_seen: str | None


class SentryIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.SENTRY]
    extra: SentryIssueSignalExtra


class RollbarItemSignalExtra(SignalExtraBase):
    level: str | None
    status: str | None
    environment: str | None
    framework: str | None
    last_occurrence_timestamp: str | None


class RollbarItemSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.ROLLBAR]
    extra: RollbarItemSignalExtra


class BugsnagErrorSignalExtra(SignalExtraBase):
    severity: str | None
    status: str | None
    context: str | None
    first_seen: str | None
    last_seen: str | None


class BugsnagErrorSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.BUGSNAG]
    extra: BugsnagErrorSignalExtra


class HoneybadgerFaultSignalExtra(SignalExtraBase):
    environment: str | None
    component: str | None
    action: str | None
    tags: list
    url: str | None
    created_at: str | None


class HoneybadgerFaultSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.HONEYBADGER]
    extra: HoneybadgerFaultSignalExtra


class RaygunErrorGroupSignalExtra(SignalExtraBase):
    status: str | None
    application_url: str | None
    last_occurred_at: str | None
    created_at: str | None


class RaygunErrorGroupSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.RAYGUN]
    extra: RaygunErrorGroupSignalExtra


class DatadogSignalExtra(SignalExtraBase):
    # One schema serves every Datadog table, because a variant is keyed by (source_product, source_type).
    # `kind` says which record kind the signal came from.
    # Each emitter fills only the fields its kind has, so every field except `kind` is optional.
    kind: Literal["incident", "error_tracking_issue", "error_span", "error_log", "monitor_alert"]
    severity: str | None = None
    state: str | None = None
    created: str | None = None
    service: str | None = None
    platform: str | None = None
    file_path: str | None = None
    function_name: str | None = None
    error_type: str | None = None
    resource_name: str | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    is_crash: str | None = None
    window_total_count: str | None = None
    window_impacted_users: str | None = None
    occurrences: str | None = None
    monitor_id: str | None = None
    monitor_type: str | None = None
    priority: str | None = None
    alert_url: str | None = None


class DatadogSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.DATADOG]
    extra: DatadogSignalExtra


# ── Tier-2 security scanners + Tier-3 feedback/reviews ────────────────────────────


class SnykScannerFindingSignalExtra(SignalExtraBase):
    effective_severity_level: str | None
    status: str | None
    type: str | None
    created_at: str | None


class SnykScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.SNYK]
    extra: SnykScannerFindingSignalExtra


class SonarqubeScannerFindingSignalExtra(SignalExtraBase):
    severity: str | None
    type: str | None
    status: str | None
    component: str | None
    rule: str | None
    creation_date: str | None


class SonarqubeScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.SONARQUBE]
    extra: SonarqubeScannerFindingSignalExtra


class SemgrepScannerFindingSignalExtra(SignalExtraBase):
    severity: str | None
    confidence: str | None
    status: str | None
    state: str | None
    created_at: str | None


class SemgrepScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.SEMGREP]
    extra: SemgrepScannerFindingSignalExtra


class Rapid7InsightvmScannerFindingSignalExtra(SignalExtraBase):
    severity: str | None
    cvss_v3_score: str | None
    published: str | None
    added: str | None


class Rapid7InsightvmScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.RAPID7_INSIGHTVM]
    extra: Rapid7InsightvmScannerFindingSignalExtra


class FeaturebaseFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    tags: list
    upvotes: str | None
    created_at: str | None


class FeaturebaseFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.FEATUREBASE]
    extra: FeaturebaseFeedbackSignalExtra


class FrillFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    vote_count: str | None
    topics: list
    created_at: str | None


class FrillFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.FRILL]
    extra: FrillFeedbackSignalExtra


class AhaFeedbackSignalExtra(SignalExtraBase):
    workflow_status: str | None
    score: str | None
    votes: str | None
    url: str | None
    created_at: str | None


class AhaFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.AHA]
    extra: AhaFeedbackSignalExtra


class UservoiceFeedbackSignalExtra(SignalExtraBase):
    state: str | None
    vote_count: str | None
    category_name: str | None
    created_at: str | None


class UservoiceFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.USERVOICE]
    extra: UservoiceFeedbackSignalExtra


class ProductboardFeedbackSignalExtra(SignalExtraBase):
    state: str | None
    tags: list
    display_url: str | None
    created_at: str | None


class ProductboardFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.PRODUCTBOARD]
    extra: ProductboardFeedbackSignalExtra


class CannyFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    tags: list
    score: str | None
    vote_count: str | None
    url: str | None
    created: str | None


class CannyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.CANNY]
    extra: CannyFeedbackSignalExtra


class AsknicelyFeedbackSignalExtra(SignalExtraBase):
    score: str | None
    status: str | None
    question_type: str | None
    segment: str | None
    created: str | None


class AsknicelyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.ASKNICELY]
    extra: AsknicelyFeedbackSignalExtra


class RetentlyFeedbackSignalExtra(SignalExtraBase):
    score: str | None
    rating_category: str | None
    feedback_topics: list
    resolved: str | None
    created_date: str | None


class RetentlyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.RETENTLY]
    extra: RetentlyFeedbackSignalExtra


class UsersnapFeedbackSignalExtra(SignalExtraBase):
    feedback_number: str | None
    public_link: str | None
    status_type: str | None
    priority: str | None
    created_at: str | None
    labels: list


class UsersnapFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.USERSNAP]
    extra: UsersnapFeedbackSignalExtra


class TypeformFeedbackSignalExtra(SignalExtraBase):
    form_id: str | None
    submitted_at: str | None


class TypeformFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.TYPEFORM]
    extra: TypeformFeedbackSignalExtra


class QualtricsFeedbackSignalExtra(SignalExtraBase):
    survey_id: str | None
    recorded_date: str | None
    finished: str | None


class QualtricsFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.QUALTRICS]
    extra: QualtricsFeedbackSignalExtra


class SurveymonkeyFeedbackSignalExtra(SignalExtraBase):
    survey_id: str | None
    date_created: str | None
    response_status: str | None


class SurveymonkeyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.SURVEYMONKEY]
    extra: SurveymonkeyFeedbackSignalExtra


class FormbricksFeedbackSignalExtra(SignalExtraBase):
    survey_id: str | None
    finished: str | None
    created_at: str | None


class FormbricksFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.FORMBRICKS]
    extra: FormbricksFeedbackSignalExtra


class SurvicateFeedbackSignalExtra(SignalExtraBase):
    survey_id: str | None
    collected_at: str | None
    url: str | None


class SurvicateFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.SURVICATE]
    extra: SurvicateFeedbackSignalExtra


class SurveysparrowFeedbackSignalExtra(SignalExtraBase):
    survey_id: str | None
    completed: str | None
    completed_time: str | None


class SurveysparrowFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.SURVEYSPARROW]
    extra: SurveysparrowFeedbackSignalExtra


class AppfiguresReviewSignalExtra(SignalExtraBase):
    stars: str | None
    version: str | None
    product: str | None
    date: str | None


class AppfiguresReviewSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.REVIEW]
    source_product: Literal[SignalSourceProduct.APPFIGURES]
    extra: AppfiguresReviewSignalExtra


class AppfollowReviewSignalExtra(SignalExtraBase):
    rating: str | None
    store: str | None
    app_version: str | None
    date: str | None


class AppfollowReviewSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.REVIEW]
    source_product: Literal[SignalSourceProduct.APPFOLLOW]
    extra: AppfollowReviewSignalExtra


class JudgemeReviewsReviewSignalExtra(SignalExtraBase):
    rating: str | None
    product_title: str | None
    verified: str | None
    created_at: str | None


class JudgemeReviewsReviewSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.REVIEW]
    source_product: Literal[SignalSourceProduct.JUDGEME_REVIEWS]
    extra: JudgemeReviewsReviewSignalExtra


# ── OAuth-connected support sources ───────────────────────────────────────────────


class IntercomTicketSignalExtra(SignalExtraBase):
    state: str | None
    priority: str | None
    admin_assignee_id: str | None
    created_at: str | None


class IntercomTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.INTERCOM]
    extra: IntercomTicketSignalExtra


class HubspotTicketSignalExtra(SignalExtraBase):
    hs_ticket_priority: str | None
    hs_pipeline_stage: str | None
    hs_ticket_category: str | None
    createdate: str | None


class HubspotTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.HUBSPOT]
    extra: HubspotTicketSignalExtra


class Dynamics365TicketSignalExtra(SignalExtraBase):
    ticketnumber: str | None
    prioritycode: str | None
    severitycode: str | None
    casetypecode: str | None
    statuscode: str | None
    createdon: str | None


class Dynamics365TicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.DYNAMICS365]
    extra: Dynamics365TicketSignalExtra


class ZohoCrmTicketSignalExtra(SignalExtraBase):
    case_number: str | None
    status: str | None
    priority: str | None
    type: str | None
    case_origin: str | None
    case_reason: str | None
    created_time: str | None


class ZohoCrmTicketSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.ZOHO_CRM]
    extra: ZohoCrmTicketSignalExtra


# ── Search analytics ──────────────────────────────────────────────────────────────


class GoogleSearchConsoleSearchOpportunitySignalExtra(SignalExtraBase):
    page: str
    query: str
    date: str
    clicks: int
    impressions: int
    ctr: float
    position: float


class GoogleSearchConsoleSearchOpportunitySignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SEARCH_OPPORTUNITY]
    source_product: Literal[SignalSourceProduct.GOOGLE_SEARCH_CONSOLE]
    extra: GoogleSearchConsoleSearchOpportunitySignalExtra


class HelpscoutConversationSignalExtra(SignalExtraBase):
    number: str | None
    status: str | None
    state: str | None
    type: str | None
    created_at: str | None


class HelpscoutConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.HELPSCOUT]
    extra: HelpscoutConversationSignalExtra


class DecagonConversationSignalExtra(SignalExtraBase):
    csat_rating: str | None
    tags: list
    created_at: str | None


class DecagonConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.DECAGON]
    extra: DecagonConversationSignalExtra


class VitallyConversationSignalExtra(SignalExtraBase):
    external_url: str | None
    created_at: str | None


class VitallyConversationSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.TICKET]
    source_product: Literal[SignalSourceProduct.VITALLY]
    extra: VitallyConversationSignalExtra


# ── Incident management / on-call ─────────────────────────────────────────────────


class PagerdutyIncidentSignalExtra(SignalExtraBase):
    status: str | None
    urgency: str | None
    html_url: str | None
    created_at: str | None


class PagerdutyIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.PAGERDUTY]
    extra: PagerdutyIncidentSignalExtra


class OpsgenieAlertSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    tags: list
    source: str | None
    created_at: str | None


class OpsgenieAlertSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.OPSGENIE]
    extra: OpsgenieAlertSignalExtra


class IncidentIoIncidentSignalExtra(SignalExtraBase):
    severity_name: str | None
    status_name: str | None
    mode: str | None
    permalink: str | None
    created_at: str | None


class IncidentIoIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.INCIDENT_IO]
    extra: IncidentIoIncidentSignalExtra


class FirehydrantIncidentSignalExtra(SignalExtraBase):
    severity: str | None
    priority: str | None
    current_milestone: str | None
    incident_url: str | None
    created_at: str | None


class FirehydrantIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.FIREHYDRANT]
    extra: FirehydrantIncidentSignalExtra


class SquadcastIncidentSignalExtra(SignalExtraBase):
    status: str | None
    priority: str | None
    url: str | None
    created_at: str | None


class SquadcastIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.SQUADCAST]
    extra: SquadcastIncidentSignalExtra


class ServicenowIncidentSignalExtra(SignalExtraBase):
    number: str | None
    state: str | None
    priority: str | None
    urgency: str | None
    impact: str | None
    category: str | None
    sys_created_on: str | None


class ServicenowIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.SERVICENOW]
    extra: ServicenowIncidentSignalExtra


class SolarwindsServiceDeskIncidentSignalExtra(SignalExtraBase):
    number: str | None
    state: str | None
    priority: str | None
    category_name: str | None
    created_at: str | None


class SolarwindsServiceDeskIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.SOLARWINDS_SERVICE_DESK]
    extra: SolarwindsServiceDeskIncidentSignalExtra


class GrafanaIrmIncidentSignalExtra(SignalExtraBase):
    status: str | None
    severity_label: str | None
    created_time: str | None


class GrafanaIrmIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.GRAFANA_IRM]
    extra: GrafanaIrmIncidentSignalExtra


class XmattersIncidentSignalExtra(SignalExtraBase):
    incident_identifier: str | None
    severity: str | None
    status: str | None
    created_at: str | None


class XmattersIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.XMATTERS]
    extra: XmattersIncidentSignalExtra


# ── Security tools (scanner_finding) ──────────────────────────────────────────────


class LaceworkScannerFindingSignalExtra(SignalExtraBase):
    alert_type: str | None
    severity: str | None
    status: str | None
    internet_exposure: str | None
    start_time: str | None


class LaceworkScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.LACEWORK]
    extra: LaceworkScannerFindingSignalExtra


class OrcaSecurityScannerFindingSignalExtra(SignalExtraBase):
    category: str | None
    risk_level: str | None
    orca_score: str | None
    status: str | None
    source: str | None
    created_at: str | None


class OrcaSecurityScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.ORCA_SECURITY]
    extra: OrcaSecurityScannerFindingSignalExtra


class TenableVulnerabilityManagementScannerFindingSignalExtra(SignalExtraBase):
    asset_uuid: str | None
    plugin_id: str | None
    port_number: str | None
    protocol: str | None
    plugin_cvss3_base_score: str | None
    severity: str | None
    state: str | None
    first_found: str | None


class TenableVulnerabilityManagementScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.TENABLE_VULNERABILITY_MANAGEMENT]
    extra: TenableVulnerabilityManagementScannerFindingSignalExtra


class BetterstackIncidentSignalExtra(SignalExtraBase):
    url: str | None
    started_at: str | None


class BetterstackIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.BETTERSTACK]
    extra: BetterstackIncidentSignalExtra


class AsanaIssueSignalExtra(SignalExtraBase):
    url: str | None
    resource_subtype: str | None
    created_at: str | None
    projects: list[str]
    tags: list[str]


class AsanaIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.ASANA]
    extra: AsanaIssueSignalExtra


class MondayIssueSignalExtra(SignalExtraBase):
    state: str | None
    group: str | None
    board_id: str | None
    created_at: str | None


class MondayIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.MONDAY]
    extra: MondayIssueSignalExtra


class PlaneIssueSignalExtra(SignalExtraBase):
    identifier: str | None
    sequence_id: str | None
    priority: str | None
    created_at: str | None


class PlaneIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.PLANE]
    extra: PlaneIssueSignalExtra


class AzureDevopsIssueSignalExtra(SignalExtraBase):
    work_item_type: str | None
    state: str | None
    priority: str | None
    created_at: str | None


class AzureDevopsIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.AZURE_DEVOPS]
    extra: AzureDevopsIssueSignalExtra


class MonteCarloAlertSignalExtra(SignalExtraBase):
    type: str | None
    status: str | None
    severity: str | None
    priority: str | None
    url: str | None
    created_time: str | None


class MonteCarloAlertSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.MONTE_CARLO]
    extra: MonteCarloAlertSignalExtra


class BigeyeIssueSignalExtra(SignalExtraBase):
    current_status: str | None
    priority: str | None
    opened_time_seconds: str | None


class BigeyeIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.BIGEYE]
    extra: BigeyeIssueSignalExtra


# ── Incident monitoring ────────────────────────────────────────────────────────


class DynatraceIncidentSignalExtra(SignalExtraBase):
    display_id: str | None
    status: str | None
    severity_level: str | None
    impact_level: str | None
    start_time: str | None
    root_cause_entity: str | None
    affected_entities: list[str]


class DynatraceIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.DYNATRACE]
    extra: DynatraceIncidentSignalExtra


class StatuspageIncidentSignalExtra(SignalExtraBase):
    status: str | None
    impact: str | None
    shortlink: str | None
    created_at: str | None


class StatuspageIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.STATUSPAGE]
    extra: StatuspageIncidentSignalExtra


class CronitorIncidentSignalExtra(SignalExtraBase):
    severity: str | None
    state: str | None
    created: str | None
    started: str | None


class CronitorIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.CRONITOR]
    extra: CronitorIncidentSignalExtra


class InstatusIncidentSignalExtra(SignalExtraBase):
    status: str | None
    started: str | None
    components: list[str]


class InstatusIncidentSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.INCIDENT]
    source_product: Literal[SignalSourceProduct.INSTATUS]
    extra: InstatusIncidentSignalExtra


class GooglePlayConsoleIssueSignalExtra(SignalExtraBase):
    issue_type: str | None
    code_location: str | None
    report_count: str | None
    affected_users: str | None
    first_version: str | None
    last_version: str | None
    last_report_time: str | None
    issue_url: str | None


class GooglePlayConsoleIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.GOOGLE_PLAY_CONSOLE]
    extra: GooglePlayConsoleIssueSignalExtra


class AzureApplicationInsightsIssueSignalExtra(SignalExtraBase):
    problem_id: str | None
    exception_type: str | None
    role_name: str | None
    occurrences: str | None
    first_seen: str | None
    last_seen: str | None


class AzureApplicationInsightsIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.AZURE_APPLICATION_INSIGHTS]
    extra: AzureApplicationInsightsIssueSignalExtra


class AppsignalIssueSignalExtra(SignalExtraBase):
    state: str | None
    severity: str | None
    namespace: str | None
    occurrence_count: str | None
    created_at: str | None
    last_occurred_at: str | None


class AppsignalIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.APPSIGNAL]
    extra: AppsignalIssueSignalExtra


class CursorIssueSignalExtra(SignalExtraBase):
    repo: str | None
    pr_number: str | None
    commit_sha: str | None
    bugs_found: str | None
    publication_status: str | None
    timestamp: str | None


class CursorIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.CURSOR]
    extra: CursorIssueSignalExtra


# ── Error monitors ─────────────────────────────────────────────────────────────


class TriggerDevErrorSignalExtra(SignalExtraBase):
    task_identifier: str | None
    status: str | None
    count: str | None
    first_seen: str | None
    last_seen: str | None


class TriggerDevErrorSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.TRIGGER_DEV]
    extra: TriggerDevErrorSignalExtra


class ChecklyErrorGroupSignalExtra(SignalExtraBase):
    check_id: str | None
    error_hash: str | None
    first_seen: str | None
    last_seen: str | None


class ChecklyErrorGroupSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.CHECKLY]
    extra: ChecklyErrorGroupSignalExtra


class RoarkIssueSignalExtra(SignalExtraBase):
    severity: str | None
    status: str | None
    event_count: str | None
    created_at: str | None


class RoarkIssueSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.ROARK]
    extra: RoarkIssueSignalExtra


# ── Community, survey, docs feedback and reviews ──────────────────────────────────


class SleekplanFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    type: str | None
    total_up: str | None
    created: str | None


class SleekplanFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.SLEEKPLAN]
    extra: SleekplanFeedbackSignalExtra


class BettermodeFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    url: str | None
    created_at: str | None


class BettermodeFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.BETTERMODE]
    extra: BettermodeFeedbackSignalExtra


class DiscourseFeedbackSignalExtra(SignalExtraBase):
    topic_id: str | None
    category_id: str | None
    created_at: str | None


class DiscourseFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.DISCOURSE]
    extra: DiscourseFeedbackSignalExtra


class MintlifyFeedbackSignalExtra(SignalExtraBase):
    path: str | None
    helpful: str | None
    status: str | None
    source: str | None
    created_at: str | None


class MintlifyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.MINTLIFY]
    extra: MintlifyFeedbackSignalExtra


class LangsmithFeedbackSignalExtra(SignalExtraBase):
    key: str | None
    score: str | None
    value: str | None
    run_id: str | None
    trace_id: str | None
    created_at: str | None


class LangsmithFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.LANGSMITH]
    extra: LangsmithFeedbackSignalExtra


class SprigFeedbackSignalExtra(SignalExtraBase):
    question_type: str | None
    survey_id: str | None
    created_at: str | None


class SprigFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.SPRIG]
    extra: SprigFeedbackSignalExtra


class GainsightPxFeedbackSignalExtra(SignalExtraBase):
    score: str | None
    question_type: str | None
    content_type: str | None
    engagement_id: str | None
    date: str | None


class GainsightPxFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.GAINSIGHT_PX]
    extra: GainsightPxFeedbackSignalExtra


class TrustpilotReviewSignalExtra(SignalExtraBase):
    stars: str | None
    language: str | None
    status: str | None
    source: str | None
    created_at: str | None


class TrustpilotReviewSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.REVIEW]
    source_product: Literal[SignalSourceProduct.TRUSTPILOT]
    extra: TrustpilotReviewSignalExtra


class OkendoReviewSignalExtra(SignalExtraBase):
    rating: str | None
    status: str | None
    product_name: str | None
    is_recommended: str | None
    date_created: str | None


class OkendoReviewSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.REVIEW]
    source_product: Literal[SignalSourceProduct.OKENDO]
    extra: OkendoReviewSignalExtra


# ── Cloud security ────────────────────────────────────────────────────────────────


class AwsSecurityHubScannerFindingSignalExtra(SignalExtraBase):
    severity_label: str | None
    compliance_status: str | None
    workflow_status: str | None
    record_state: str | None
    region: str | None
    created_at: str | None


class AwsSecurityHubScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.AWS_SECURITY_HUB]
    extra: AwsSecurityHubScannerFindingSignalExtra


class AwsGuarddutyScannerFindingSignalExtra(SignalExtraBase):
    type: str | None
    severity: str | None
    region: str | None
    created_at: str | None


class AwsGuarddutyScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.AWS_GUARDDUTY]
    extra: AwsGuarddutyScannerFindingSignalExtra


class AwsInspectorScannerFindingSignalExtra(SignalExtraBase):
    type: str | None
    severity: str | None
    status: str | None
    fix_available: str | None
    exploit_available: str | None
    region: str | None
    first_observed_at: str | None


class AwsInspectorScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.AWS_INSPECTOR]
    extra: AwsInspectorScannerFindingSignalExtra


class MicrosoftDefenderCloudAppsScannerFindingSignalExtra(SignalExtraBase):
    severity_value: str | None
    resolution_status_value: str | None
    timestamp: str | None


class MicrosoftDefenderCloudAppsScannerFindingSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.SCANNER_FINDING]
    source_product: Literal[SignalSourceProduct.MICROSOFT_DEFENDER_CLOUD_APPS]
    extra: MicrosoftDefenderCloudAppsScannerFindingSignalExtra


# ── Union over all signal variants ──────────────────────────────────────────────
# Discrimination is by the composite (source_product, source_type) pair, resolved via
# SIGNAL_VARIANT_LOOKUP below — a single-field pydantic discriminator can't express it
# because llm_analytics/error_tracking map several (product, type) pairs to one variant and
# github/linear/pganalyze share source_type="issue".

SignalInput = Annotated[
    SessionProblemSignalInput
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
    | CheckFailedSignalInput
    | LogsAlertStateChangeSignalInput
    | AnalyticsAnomalyInvestigationSignalInput
    | HealthCheckSignalInput
    | ReplayVisionScannerFindingSignalInput
    | FreshdeskTicketSignalInput
    | FreshserviceTicketSignalInput
    | FrontConversationSignalInput
    | GorgiasTicketSignalInput
    | KustomerConversationSignalInput
    | DixaConversationSignalInput
    | PlainThreadSignalInput
    | GitlabIssueSignalInput
    | GiteaIssueSignalInput
    | ShortcutStorySignalInput
    | SentryIssueSignalInput
    | RollbarItemSignalInput
    | BugsnagErrorSignalInput
    | HoneybadgerFaultSignalInput
    | RaygunErrorGroupSignalInput
    | DatadogSignalInput
    | SnykScannerFindingSignalInput
    | SonarqubeScannerFindingSignalInput
    | SemgrepScannerFindingSignalInput
    | Rapid7InsightvmScannerFindingSignalInput
    | FeaturebaseFeedbackSignalInput
    | FrillFeedbackSignalInput
    | AhaFeedbackSignalInput
    | UservoiceFeedbackSignalInput
    | ProductboardFeedbackSignalInput
    | CannyFeedbackSignalInput
    | AsknicelyFeedbackSignalInput
    | RetentlyFeedbackSignalInput
    | UsersnapFeedbackSignalInput
    | TypeformFeedbackSignalInput
    | QualtricsFeedbackSignalInput
    | SurveymonkeyFeedbackSignalInput
    | FormbricksFeedbackSignalInput
    | SurvicateFeedbackSignalInput
    | SurveysparrowFeedbackSignalInput
    | AppfiguresReviewSignalInput
    | AppfollowReviewSignalInput
    | JudgemeReviewsReviewSignalInput
    | IntercomTicketSignalInput
    | HubspotTicketSignalInput
    | Dynamics365TicketSignalInput
    | ZohoCrmTicketSignalInput
    | EngineeringAnalyticsCIFlakyCheckSignalInput
    | EngineeringAnalyticsCIBrokenDefaultBranchSignalInput
    | EngineeringAnalyticsCIDurationRegressionSignalInput
    | GoogleSearchConsoleSearchOpportunitySignalInput
    | HelpscoutConversationSignalInput
    | DecagonConversationSignalInput
    | VitallyConversationSignalInput
    | PagerdutyIncidentSignalInput
    | OpsgenieAlertSignalInput
    | IncidentIoIncidentSignalInput
    | FirehydrantIncidentSignalInput
    | SquadcastIncidentSignalInput
    | ServicenowIncidentSignalInput
    | SolarwindsServiceDeskIncidentSignalInput
    | GrafanaIrmIncidentSignalInput
    | XmattersIncidentSignalInput
    | BetterstackIncidentSignalInput
    | AsanaIssueSignalInput
    | MondayIssueSignalInput
    | PlaneIssueSignalInput
    | AzureDevopsIssueSignalInput
    | MonteCarloAlertSignalInput
    | BigeyeIssueSignalInput
    | DynatraceIncidentSignalInput
    | StatuspageIncidentSignalInput
    | CronitorIncidentSignalInput
    | InstatusIncidentSignalInput
    | LaceworkScannerFindingSignalInput
    | OrcaSecurityScannerFindingSignalInput
    | TenableVulnerabilityManagementScannerFindingSignalInput
    | GooglePlayConsoleIssueSignalInput
    | AzureApplicationInsightsIssueSignalInput
    | AppsignalIssueSignalInput
    | CursorIssueSignalInput
    | TriggerDevErrorSignalInput
    | ChecklyErrorGroupSignalInput
    | RoarkIssueSignalInput
    | SleekplanFeedbackSignalInput
    | BettermodeFeedbackSignalInput
    | DiscourseFeedbackSignalInput
    | MintlifyFeedbackSignalInput
    | LangsmithFeedbackSignalInput
    | SprigFeedbackSignalInput
    | GainsightPxFeedbackSignalInput
    | TrustpilotReviewSignalInput
    | OkendoReviewSignalInput
    | AwsSecurityHubScannerFindingSignalInput
    | AwsGuarddutyScannerFindingSignalInput
    | AwsInspectorScannerFindingSignalInput
    | MicrosoftDefenderCloudAppsScannerFindingSignalInput,
    Field(union_mode="left_to_right"),
]

SIGNAL_INPUT_VARIANTS: tuple[type[SignalInputBase], ...] = (
    SessionProblemSignalInput,
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
    AnalyticsAnomalyInvestigationSignalInput,
    HealthCheckSignalInput,
    ReplayVisionScannerFindingSignalInput,
    FreshdeskTicketSignalInput,
    FreshserviceTicketSignalInput,
    FrontConversationSignalInput,
    GorgiasTicketSignalInput,
    KustomerConversationSignalInput,
    DixaConversationSignalInput,
    PlainThreadSignalInput,
    GitlabIssueSignalInput,
    GiteaIssueSignalInput,
    ShortcutStorySignalInput,
    SentryIssueSignalInput,
    RollbarItemSignalInput,
    BugsnagErrorSignalInput,
    HoneybadgerFaultSignalInput,
    RaygunErrorGroupSignalInput,
    DatadogSignalInput,
    SnykScannerFindingSignalInput,
    SonarqubeScannerFindingSignalInput,
    SemgrepScannerFindingSignalInput,
    Rapid7InsightvmScannerFindingSignalInput,
    FeaturebaseFeedbackSignalInput,
    FrillFeedbackSignalInput,
    AhaFeedbackSignalInput,
    UservoiceFeedbackSignalInput,
    ProductboardFeedbackSignalInput,
    CannyFeedbackSignalInput,
    AsknicelyFeedbackSignalInput,
    RetentlyFeedbackSignalInput,
    UsersnapFeedbackSignalInput,
    TypeformFeedbackSignalInput,
    QualtricsFeedbackSignalInput,
    SurveymonkeyFeedbackSignalInput,
    FormbricksFeedbackSignalInput,
    SurvicateFeedbackSignalInput,
    SurveysparrowFeedbackSignalInput,
    AppfiguresReviewSignalInput,
    AppfollowReviewSignalInput,
    JudgemeReviewsReviewSignalInput,
    IntercomTicketSignalInput,
    HubspotTicketSignalInput,
    Dynamics365TicketSignalInput,
    ZohoCrmTicketSignalInput,
    EngineeringAnalyticsCIFlakyCheckSignalInput,
    EngineeringAnalyticsCIBrokenDefaultBranchSignalInput,
    EngineeringAnalyticsCIDurationRegressionSignalInput,
    GoogleSearchConsoleSearchOpportunitySignalInput,
    HelpscoutConversationSignalInput,
    DecagonConversationSignalInput,
    VitallyConversationSignalInput,
    PagerdutyIncidentSignalInput,
    OpsgenieAlertSignalInput,
    IncidentIoIncidentSignalInput,
    FirehydrantIncidentSignalInput,
    SquadcastIncidentSignalInput,
    ServicenowIncidentSignalInput,
    SolarwindsServiceDeskIncidentSignalInput,
    GrafanaIrmIncidentSignalInput,
    XmattersIncidentSignalInput,
    BetterstackIncidentSignalInput,
    AsanaIssueSignalInput,
    MondayIssueSignalInput,
    PlaneIssueSignalInput,
    AzureDevopsIssueSignalInput,
    MonteCarloAlertSignalInput,
    BigeyeIssueSignalInput,
    DynatraceIncidentSignalInput,
    StatuspageIncidentSignalInput,
    CronitorIncidentSignalInput,
    InstatusIncidentSignalInput,
    LaceworkScannerFindingSignalInput,
    OrcaSecurityScannerFindingSignalInput,
    TenableVulnerabilityManagementScannerFindingSignalInput,
    GooglePlayConsoleIssueSignalInput,
    AzureApplicationInsightsIssueSignalInput,
    AppsignalIssueSignalInput,
    CursorIssueSignalInput,
    TriggerDevErrorSignalInput,
    ChecklyErrorGroupSignalInput,
    RoarkIssueSignalInput,
    SleekplanFeedbackSignalInput,
    BettermodeFeedbackSignalInput,
    DiscourseFeedbackSignalInput,
    MintlifyFeedbackSignalInput,
    LangsmithFeedbackSignalInput,
    SprigFeedbackSignalInput,
    GainsightPxFeedbackSignalInput,
    TrustpilotReviewSignalInput,
    OkendoReviewSignalInput,
    AwsSecurityHubScannerFindingSignalInput,
    AwsGuarddutyScannerFindingSignalInput,
    AwsInspectorScannerFindingSignalInput,
    MicrosoftDefenderCloudAppsScannerFindingSignalInput,
    CheckFailedSignalInput,
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
