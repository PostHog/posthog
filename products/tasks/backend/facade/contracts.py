"""
Contract types for the tasks product.

Stable, framework-free frozen dataclasses describing the data the tasks product
exposes across product boundaries. No Django, no DRF — just stdlib/pydantic types.

These use ``pydantic.dataclasses.dataclass`` (same shape as the stdlib variant, but
with runtime validation on construction) so a malformed mapper surfaces a
``ValidationError`` at the boundary instead of a confusing failure deep in a caller.

Behavioral/wiring surfaces (sandbox classes, the multi-turn agent machinery, temporal
workflows, max tools, webhook handlers) are NOT data and are not modelled here — they
cross the boundary through sibling facade submodules (``sandbox``, ``warm``,
``agents``, ``temporal``, ``max_tools``, ``webhooks``, …), with DTOs here only for
their data results.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TaskDTO:
    """A code task."""

    id: UUID
    team_id: int
    title: str
    description: str
    origin_product: str
    repository: str | None
    internal: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    created_by_id: int | None = None
    task_number: int | None = None
    slug: str = ""


@dataclass(frozen=True)
class TaskRunDTO:
    """A single execution of a task.

    Carries the derived fields external callers read off a ``TaskRun`` ORM instance
    (``is_terminal``, ``workflow_id``, ``mode``) plus a few denormalised parent-task
    values (``task_origin_product``, ``created_by_distinct_id``, ``pr_url``) so callers
    never need to traverse the ORM relation themselves.
    """

    id: UUID
    task_id: UUID
    team_id: int
    status: str
    environment: str
    stage: str | None
    branch: str | None
    error_message: str | None
    output: dict | None
    state: dict
    artifacts: list = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    is_terminal: bool = False
    workflow_id: str = ""
    mode: str = "background"
    task_origin_product: str | None = None
    created_by_id: int | None = None
    created_by_distinct_id: str | None = None
    pr_url: str | None = None


@dataclass(frozen=True)
class WarmRunDTO:
    """Outcome of ensuring a warm sandbox run exists for a task."""

    task_id: UUID
    run_id: UUID
    run_status: str
    just_created: bool


@dataclass(frozen=True)
class TaskDetailDTO:
    """The HTTP detail representation of a task.

    Mirrors exactly the fields ``TaskSerializer`` emits, in order. ``github_integration`` and
    ``github_user_integration`` are the integration primary keys (or ``None``), matching the
    original ``PrimaryKeyRelatedField`` output. ``signal_report`` is the linked report id (or
    ``None``). ``latest_run`` is the most-recent run as a ``TaskRunDetailDTO`` (or ``None``).
    ``latest_run_id`` carries just that run's id for the conversation envelope, which needs the id
    to reconnect to sandbox logs but not the full (presigned-log) run payload. ``created_by``
    mirrors core ``UserBasicSerializer`` output.
    """

    id: UUID
    task_number: int | None
    slug: str
    title: str
    title_manually_set: bool
    description: str
    origin_product: str
    repository: str | None
    github_integration: int | None
    github_user_integration: UUID | None
    signal_report: UUID | None
    json_schema: dict | None
    internal: bool
    archived: bool
    archived_at: datetime | None
    ci_prompt: str | None
    latest_run: "TaskRunDetailDTO | None" = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: "TaskUserBasicInfo | None" = None
    latest_run_id: UUID | None = None
    channel: UUID | None = None


@dataclass(frozen=True)
class ChannelDTO:
    """The HTTP representation of a task channel."""

    id: UUID
    name: str
    channel_type: str
    created_at: datetime
    created_by: "TaskUserBasicInfo | None" = None


@dataclass(frozen=True)
class TaskThreadMessageDTO:
    """The HTTP representation of one message in a task's thread."""

    id: UUID
    task: UUID
    content: str
    created_at: datetime
    author: "TaskUserBasicInfo | None" = None
    forwarded_to_agent_at: datetime | None = None
    forwarded_by: "TaskUserBasicInfo | None" = None


@dataclass(frozen=True)
class TaskMentionDTO:
    """One @-mention of the requesting user in a task's thread, for the mentions feed."""

    id: UUID
    message_id: UUID
    task_id: UUID
    task_title: str
    channel_id: UUID | None
    channel_name: str | None
    content: str
    created_at: datetime
    author: "TaskUserBasicInfo | None" = None


@dataclass(frozen=True)
class TaskLatestRunSummaryDTO:
    """The latest-run status/environment pair nested in a task summary response."""

    status: str | None
    environment: str | None


@dataclass(frozen=True)
class TaskSummaryDTO:
    """The HTTP summary representation of a task.

    Mirrors exactly the fields ``TaskSummarySerializer`` emits. ``latest_run`` carries the
    most-recent run's ``status`` and ``environment`` (or ``None`` when the task has no runs).
    """

    id: UUID
    title: str
    repository: str | None
    created_at: datetime
    updated_at: datetime
    origin_product: str = ""
    latest_run: TaskLatestRunSummaryDTO | None = None


@dataclass(frozen=True)
class TaskValidationError:
    """A structured validation-error payload the presentation layer renders as a 400/404.

    ``kind`` distinguishes the response shape the original task views built:
      - ``"validation_error"`` -> the ``{type, code, detail, attr}`` body.
      - ``"detail"`` -> a plain ``{"detail": detail}`` body.
      - ``"error"`` -> the ``{"error": detail}`` body.
    ``missing_artifact_ids`` is included on the body only when set.
    """

    kind: str
    detail: str
    code: str | None = None
    attr: str | None = None
    missing_artifact_ids: list[str] | None = None


@dataclass(frozen=True)
class TaskRunResult:
    """Outcome of the task ``run`` action.

    Exactly one of ``task`` / ``error`` is set. ``task`` is the refreshed task detail DTO with
    its new latest run; ``error`` carries the structured error the original view returned inline.
    """

    task: "TaskDetailDTO | None" = None
    error: TaskValidationError | None = None


@dataclass(frozen=True)
class StagedArtifactPreparedDTO:
    """One prepared staged upload, mirroring ``TaskStagedArtifactPrepareUploadResponseSerializer``."""

    id: str
    name: str
    type: str
    source: str
    size: int
    content_type: str
    storage_path: str
    expires_in: int
    presigned_post: dict
    metadata: dict | None = None


@dataclass(frozen=True)
class StagedArtifactPrepareResult:
    """Outcome of preparing staged uploads. ``error`` is set when a presigned POST could not be minted."""

    artifacts: list[StagedArtifactPreparedDTO] | None = None
    error: str | None = None


@dataclass(frozen=True)
class StagedArtifactFinalizeResult:
    """Outcome of finalizing staged uploads. ``error`` is set on the first invalid/missing artifact."""

    artifacts: list[dict] | None = None
    error: str | None = None


@dataclass(frozen=True)
class SlackThreadContextRepoResearchDTO:
    """The internal sandbox run the discovery agent used to pick a run's repo."""

    task_id: str
    run_id: str
    status: str | None
    task_processing_workflow_id: str
    task_processing_workflow_url: str | None
    sandbox_url: str | None
    task_view_url: str
    log_url: str | None


@dataclass(frozen=True)
class SlackThreadContextRunDTO:
    """One TaskRun and its associated Temporal workflow handles for the slack-thread debug view."""

    id: str
    status: str
    created_at: datetime | None
    completed_at: datetime | None
    sandbox_url: str | None
    pr_url: str | None
    error_message: str | None
    task_processing_workflow_id: str
    task_processing_workflow_url: str | None
    mention_workflow_id: str | None
    mention_workflow_url: str | None
    task_view_url: str
    log_url: str | None
    repo_research: SlackThreadContextRepoResearchDTO | None = None


@dataclass(frozen=True)
class SlackThreadContextThreadDTO:
    """Slack-side identifiers and mapping metadata for a thread → task lookup."""

    url: str
    channel: str
    thread_ts: str
    slack_workspace_id: str | None
    mentioning_slack_user_id: str | None


@dataclass(frozen=True)
class SlackThreadContextTaskDTO:
    """The PostHog Task linked to a Slack thread."""

    id: str
    team_id: int
    title: str
    repository: str | None
    origin_product: str
    created_at: datetime | None
    url: str


@dataclass(frozen=True)
class SlackThreadContextDTO:
    """Top-level response for the slack-thread debug endpoint."""

    thread: SlackThreadContextThreadDTO
    task: SlackThreadContextTaskDTO | None = None
    runs: list[SlackThreadContextRunDTO] = Field(default_factory=list)


@dataclass(frozen=True)
class SlackThreadContextResult:
    """Outcome of resolving a slack-thread context.

    ``outcome`` is one of ``"forbidden"`` (403), ``"bad_url"`` (400), ``"no_mapping"`` (404), or
    ``"ok"`` (``context`` set). The error variants carry the partial payload the original view
    returned in the body.
    """

    outcome: str
    context: SlackThreadContextDTO | None = None
    bad_url: str | None = None
    no_mapping_thread: SlackThreadContextThreadDTO | None = None


@dataclass(frozen=True)
class TaskRunDetailDTO:
    """The HTTP detail representation of a task run.

    Mirrors exactly the fields ``TaskRunDetailSerializer`` emits, in order. ``task`` is the
    parent task id (rendered as a string, matching the original ``PrimaryKeyRelatedField``).
    The SMF-derived fields are computed in the facade mapper ``_task_run_detail_to_dto``:
    ``log_url`` is a presigned S3 URL (cached); ``runtime_adapter`` / ``provider`` / ``model`` /
    ``reasoning_effort`` are parsed off the run ``state``. ``artifacts`` carries the run's
    artifact manifest entries verbatim. Reused by the run-detail responses and nested as
    ``latest_run`` by the task detail response.
    """

    id: UUID
    task: UUID
    stage: str | None
    branch: str | None
    status: str
    environment: str
    runtime_adapter: str | None
    provider: str | None
    model: str | None
    reasoning_effort: str | None
    log_url: str | None
    error_message: str | None
    output: dict | None
    state: dict
    artifacts: list = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class TaskRunValidationError:
    """A structured validation-error payload the presentation layer renders as a 400.

    ``kind`` distinguishes the response shape the original view built:
      - ``"validation_error"`` -> the ``{type, code, detail, attr}`` body, fields carried here.
      - ``"detail"`` -> a plain ``{"detail": detail}`` body.
    """

    kind: str
    detail: str
    code: str | None = None
    attr: str | None = None


@dataclass(frozen=True)
class TaskRunCreateResult:
    """Outcome of bootstrapping a task run.

    Exactly one of ``run`` / ``error`` is set. ``error`` carries the structured validation
    error the original view returned inline; the presentation layer maps it to a 400.
    """

    run: "TaskRunDetailDTO | None" = None
    error: TaskRunValidationError | None = None


@dataclass(frozen=True)
class TaskRunStreamInfoDTO:
    """The minimal run facts the SSE stream view needs without holding a model.

    ``id`` keys the Redis stream, ``state`` decides dedicated-stream routing, and
    ``origin_product`` is the bounded metric label resolved off the parent task.
    """

    id: UUID
    state: dict
    origin_product: str


@dataclass(frozen=True)
class TaskRunSandboxConnectionDTO:
    """A run's live-sandbox connection details, for proxying agent-server commands.

    Carries the sandbox URL and connect token parsed off the run state plus a freshly-minted
    connection token. ``sandbox_url`` is ``None`` when the run has no active sandbox.
    """

    sandbox_url: str | None
    sandbox_connect_token: str | None
    connection_token: str | None = None


@dataclass(frozen=True)
class CreatedTaskDTO:
    """Result of creating-and-running a task.

    ``Task.create_and_run`` returns an ORM instance whose ``latest_run`` is read by
    callers; this contract hands back the ids (and the run, if one was created) without
    leaking the model.
    """

    task_id: UUID
    team_id: int
    latest_run: TaskRunDTO | None = None


@dataclass(frozen=True)
class CodeInviteRedeemResult:
    """Outcome of attempting to redeem a PostHog Code invite.

    ``outcome`` is one of ``redeemed`` (or ``already_redeemed``), ``invalid_code``, or
    ``not_redeemable``. The presentation layer maps it to the success/error HTTP response;
    the ORM redemption, idempotency check, count increment, and analytics capture all
    happen inside the facade so no model leaks across the boundary.
    """

    outcome: str


@dataclass(frozen=True)
class TaskAutomationDTO:
    """A scheduled task automation.

    Mirrors exactly the fields ``TaskAutomationSerializer`` emits. Most read fields are
    proxied off the underlying ``Task`` (``name``/``prompt``/``repository``/
    ``github_integration``) or derived from the linked last run (``last_run_at``/
    ``last_run_status``). ``github_integration`` is the integration's primary key (or
    ``None``). ``last_task_id`` is always present (the automation's task id as a string);
    ``last_task_run_id`` is the most recent run's id as a string, or ``None``.
    """

    id: UUID
    name: str
    prompt: str
    repository: str | None
    github_integration: int | None
    cron_expression: str
    timezone: str
    template_id: str | None
    enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    last_task_id: str
    last_task_run_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CodeWorkflowConfigDTO:
    """A user's per-team code-workflow binding configuration.

    Mirrors exactly the JSON shape the code-workflow endpoints emit: ``id`` and
    ``updatedAt`` are stringified, ``version`` powers optimistic locking, and
    ``bindings`` is the situation-id → ordered action-list mapping.
    """

    id: str
    version: int
    updated_at: datetime
    bindings: dict


@dataclass(frozen=True)
class CodeWorkflowDiagnosticDTO:
    """One binding-validation diagnostic.

    Mirrors a ``ValidationDiagnostic``; ``situation_id`` / ``action_id`` are present only
    when the diagnostic is scoped to a specific situation or action.
    """

    severity: str
    code: str
    message: str
    situation_id: str | None = None
    action_id: str | None = None


@dataclass(frozen=True)
class CodeWorkflowSaveResult:
    """Outcome of attempting to save code-workflow bindings.

    ``outcome`` is one of ``saved`` (bindings persisted, version bumped), ``conflict``
    (``expected_version`` did not match the stored version), or ``invalid`` (validation
    failed). ``config`` is always the resulting/current config; ``diagnostics`` is only
    populated on the ``invalid`` outcome.
    """

    outcome: str
    config: CodeWorkflowConfigDTO
    diagnostics: list[CodeWorkflowDiagnosticDTO] = Field(default_factory=list)


@dataclass(frozen=True)
class CodeHomeWorkstreamTaskDTO:
    """One grouped task inside a workstream card."""

    id: str | None
    title: str | None
    status: str | None
    is_generating: bool = False
    needs_permission: bool = False
    quick_action: str | None = None


@dataclass(frozen=True)
class CodeHomeWorkstreamDTO:
    """A persisted workstream card for the code-home board."""

    id: str
    repo_name: str | None
    repo_full_path: str | None
    branch: str | None
    pr_url: str | None
    pr: dict | None
    primary_situation: str | None
    last_activity_at: int
    tasks: list[CodeHomeWorkstreamTaskDTO] = Field(default_factory=list)
    situations: list = Field(default_factory=list)


@dataclass(frozen=True)
class CodeHomeActiveAgentDTO:
    """A live, in-flight agent run shown on the code-home board."""

    task_id: str
    title: str
    repo_name: str | None
    branch: str | None
    status: str
    last_activity_at: int
    needs_permission: bool = False
    cloud_pr_url: str | None = None


@dataclass(frozen=True)
class CodeHomeDTO:
    """The full code-home board: live agents plus persisted workstreams by column."""

    active_agents: list[CodeHomeActiveAgentDTO] = Field(default_factory=list)
    needs_attention: list[CodeHomeWorkstreamDTO] = Field(default_factory=list)
    in_progress: list[CodeHomeWorkstreamDTO] = Field(default_factory=list)


@dataclass(frozen=True)
class TaskUserBasicInfo:
    """Lightweight user info for display, mirroring core ``UserBasicSerializer`` output.

    Carries exactly the fields that serializer emits so presentation responses stay
    byte-identical when a task/run/environment exposes its ``created_by``.
    """

    id: int
    uuid: UUID
    distinct_id: str
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None = None
    hedgehog_config: dict | None = None
    role_at_organization: str | None = None


@dataclass(frozen=True)
class SandboxEnvironmentDTO:
    """A sandbox execution environment."""

    id: UUID
    team_id: int
    name: str
    network_access_level: str
    private: bool
    internal: bool
    include_default_domains: bool
    allowed_domains: list[str] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)
    effective_domains: list[str] = Field(default_factory=list)
    has_environment_variables: bool = False
    created_by: TaskUserBasicInfo | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    custom_image_id: UUID | None = None
    custom_image_name: str | None = None
    custom_image_status: str | None = None


@dataclass(frozen=True)
class SandboxCustomImageDTO:
    """A user-defined custom base image for cloud task sandboxes (Modal VM runtime)."""

    id: UUID
    team_id: int
    name: str
    description: str
    status: str
    version: int
    modal_image_name: str
    error: str
    repository: str = ""
    private: bool = False
    spec: dict = Field(default_factory=dict)
    spec_yaml: str = ""
    scan_result: dict = Field(default_factory=dict)
    build_log: str = ""
    builder_task_id: UUID | None = None
    created_by: TaskUserBasicInfo | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SandboxSnapshotDTO:
    """A snapshot of a sandbox image."""

    id: UUID
    external_id: str
    status: str
    repos: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class SignalReportPrUrlDTO:
    """The PR URL produced by the latest task run for a signal report."""

    report_id: str
    pr_url: str


@dataclass(frozen=True)
class WarmTaskDTO:
    """The draft Task + warm Run birthed by a Code-app warm request."""

    task_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class TaskRunGaugeRow:
    """One metric value keyed by (status, environment, origin_product)."""

    environment: str
    origin_product: str
    value: float
    status: str | None = None


@dataclass(frozen=True)
class TaskRunStateMetricsDTO:
    """Aggregations describing the current state of the TaskRun table, for monitoring gauges."""

    runs_in_status: list[TaskRunGaugeRow] = Field(default_factory=list)
    oldest_open_age_seconds: list[TaskRunGaugeRow] = Field(default_factory=list)
    created_recently: list[TaskRunGaugeRow] = Field(default_factory=list)
    terminal_recently: list[TaskRunGaugeRow] = Field(default_factory=list)
