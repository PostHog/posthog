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
    github_login: str
    github_name: str | None
    relevant_commits: list[RelevantCommit]
    user: SignalReviewerUserInfo | None
    reason: str | None = None


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
    createdAt: str | None


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
    createdAt: str | None


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
    shortId: str | None
    firstSeen: str | None


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
    applicationUrl: str | None
    lastOccurredAt: str | None
    createdAt: str | None


class RaygunErrorGroupSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.ISSUE]
    source_product: Literal[SignalSourceProduct.RAYGUN]
    extra: RaygunErrorGroupSignalExtra


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
    creationDate: str | None


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
    createdAt: str | None


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
    displayUrl: str | None
    createdAt: str | None


class ProductboardFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.PRODUCTBOARD]
    extra: ProductboardFeedbackSignalExtra


class CannyFeedbackSignalExtra(SignalExtraBase):
    status: str | None
    tags: list
    score: str | None
    voteCount: str | None
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
    ratingCategory: str | None
    feedbackTopics: list
    resolved: str | None
    createdDate: str | None


class RetentlyFeedbackSignalInput(SignalInputBase):
    source_type: Literal[SignalSourceType.FEEDBACK]
    source_product: Literal[SignalSourceProduct.RETENTLY]
    extra: RetentlyFeedbackSignalExtra


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
    | AppfiguresReviewSignalInput
    | AppfollowReviewSignalInput
    | JudgemeReviewsReviewSignalInput
    | IntercomTicketSignalInput
    | HubspotTicketSignalInput
    | EngineeringAnalyticsCIFlakyCheckSignalInput
    | EngineeringAnalyticsCIBrokenDefaultBranchSignalInput
    | EngineeringAnalyticsCIDurationRegressionSignalInput,
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
    AppfiguresReviewSignalInput,
    AppfollowReviewSignalInput,
    JudgemeReviewsReviewSignalInput,
    IntercomTicketSignalInput,
    HubspotTicketSignalInput,
    EngineeringAnalyticsCIFlakyCheckSignalInput,
    EngineeringAnalyticsCIBrokenDefaultBranchSignalInput,
    EngineeringAnalyticsCIDurationRegressionSignalInput,
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
