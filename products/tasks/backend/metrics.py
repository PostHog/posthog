from typing import TYPE_CHECKING, Literal

import structlog
from prometheus_client import Counter, Gauge, Histogram

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


TaskWorkflowStartOutcome = Literal["attempted", "blocked", "failed", "started"]
CustomImageBuildOutcome = Literal["started", "succeeded", "failed", "scan_rejected"]
DevStackImageBakeOutcome = Literal["succeeded", "bake_failed", "failed", "dispatch_failed"]
# Outcome of an SSE task-run stream connection when it closes.
#   completed         — stream reached its completion sentinel
#   stream_error      — Redis/stream error sentinel ended the connection
#   unavailable       — stream key never appeared within the wait timeout
#   client_disconnect — client went away (GeneratorExit) before completion
#   rotated           — per-connection cap reached; clean EOF, client resumes
StreamConnectionOutcome = Literal["completed", "stream_error", "unavailable", "client_disconnect", "rotated"]
_ALLOWED_MODES = {"background", "interactive"}
_ALLOWED_RUN_SOURCES = {"manual", "signal_report"}
_ALLOWED_RUNTIME_ADAPTERS = {"claude", "codex"}
_ALLOWED_TASK_RUNTIMES = {"acp", "pi"}


TASK_RUN_CREATED_TOTAL = Counter(
    "posthog_tasks_task_run_created_total",
    "TaskRun rows created by the Tasks product",
    labelnames=[
        "origin_product",
        "run_environment",
        "mode",
        "run_source",
        "task_runtime",
        "runtime_adapter",
        "prewarmed",
    ],
)

TASK_RUN_WORKFLOW_START_TOTAL = Counter(
    "posthog_tasks_task_run_workflow_start_total",
    "TaskRun workflow start lifecycle events",
    labelnames=[
        "origin_product",
        "run_environment",
        "mode",
        "run_source",
        "task_runtime",
        "runtime_adapter",
        "prewarmed",
        "outcome",
        "reason",
    ],
)

TASK_RUN_DISPATCH_CALLBACK_TOTAL = Counter(
    "posthog_tasks_task_run_dispatch_callback_total",
    "on_commit workflow-dispatch callback lifecycle: 'scheduled' when registered, 'fired' when it runs. "
    "scheduled minus fired is the count of lost callbacks that strand a run in QUEUED.",
    labelnames=[
        "origin_product",
        "run_environment",
        "mode",
        "run_source",
        "task_runtime",
        "runtime_adapter",
        "prewarmed",
        "phase",
    ],
)

WORKFLOW_DISPATCH_CREATED_TOTAL = Counter(
    "posthog_tasks_workflow_dispatch_created_total", "Workflow dispatch rows created", labelnames=["kind"]
)
WORKFLOW_DISPATCH_ATTEMPT_TOTAL = Counter(
    "posthog_tasks_workflow_dispatch_attempt_total",
    "Workflow dispatch attempt outcomes",
    labelnames=["kind", "outcome"],
)
WORKFLOW_DISPATCH_START_DURATION_SECONDS = Histogram(
    "posthog_tasks_workflow_dispatch_start_duration_seconds", "Temporal workflow start RPC duration"
)
WORKFLOW_DISPATCH_READY = Gauge("posthog_tasks_workflow_dispatch_ready", "Ready workflow dispatches")
WORKFLOW_DISPATCH_OLDEST_READY_AGE_SECONDS = Gauge(
    "posthog_tasks_workflow_dispatch_oldest_ready_age_seconds", "Age of the oldest ready workflow dispatch"
)
WORKFLOW_DISPATCH_CLAIMED = Gauge("posthog_tasks_workflow_dispatch_claimed", "Claimed workflow dispatches")
WORKFLOW_DISPATCH_LEASE_EXPIRED_TOTAL = Counter(
    "posthog_tasks_workflow_dispatch_lease_expired_total", "Expired workflow dispatch leases reclaimed"
)
WORKFLOW_DISPATCH_DEAD_TOTAL = Counter(
    "posthog_tasks_workflow_dispatch_dead_total", "Dead workflow dispatches", labelnames=["kind", "reason"]
)
WORKFLOW_DISPATCH_MISSING_INTENT_TOTAL = Counter(
    "posthog_tasks_workflow_dispatch_missing_intent_total", "Queued cloud task runs without dispatch intent"
)

AGENT_OTEL_TELEMETRY_STAMPED_TOTAL = Counter(
    "posthog_tasks_agent_otel_telemetry_stamped_total",
    "Agent-run OTel telemetry rollout decisions stamped into run state at dispatch "
    "(tasks-agent-run-otel-telemetry flag). First-time stamps only; resumes reuse the stamp.",
    labelnames=["enabled"],
)

RUN_LOG_MIRROR_ENTRIES_TOTAL = Counter(
    "posthog_tasks_run_log_mirror_entries_total",
    "Task-run log entries mirrored to stdout for the internal Logs project (run_log_mirror).",
    labelnames=["origin_product"],
)

RUN_LOG_MIRROR_OTLP_BATCHES_TOTAL = Counter(
    "posthog_tasks_run_log_mirror_otlp_batches_total",
    "Direct-OTLP mirror batch deliveries by outcome (the local-dev leg; unset in cloud).",
    labelnames=["outcome"],
)

LOG_APPEND_UNSERIALIZED_TOTAL = Counter(
    "posthog_tasks_log_append_unserialized_total",
    "Task-run log appends that ran without the per-object lock (redis unavailable, or contention "
    "past the blocking timeout), where a concurrent append can still drop entries.",
)

PREWARMED_ACTIVATED_TOTAL = Counter(
    "posthog_tasks_prewarmed_activated_total",
    "Pre-warmed Runs that received their first user message (the warm sandbox got used, not reaped)",
    labelnames=["origin_product"],
)

TASK_RUN_FAILED_TOTAL = Counter(
    "posthog_tasks_task_run_failed_total",
    "TaskRun workflow failures with bounded attribution labels",
    labelnames=[
        "origin_product",
        "mode",
        "run_source",
        "runtime_adapter",
        "error_type",
        "temporal_activity_type",
        "temporal_activity_retry_state",
        "cause_error_type",
    ],
)

CUSTOM_IMAGE_BUILD_TOTAL = Counter(
    "posthog_tasks_custom_image_build_total",
    "Custom sandbox image build lifecycle events",
    labelnames=["outcome"],
)

DEV_STACK_IMAGE_BAKE_TOTAL = Counter(
    "posthog_tasks_dev_stack_image_bake_total",
    "Prebaked dev-stack VM image bake lifecycle events",
    labelnames=["outcome", "region", "trigger"],
)


# Connection lifetimes range from a few seconds (cold reconnect) to the
# per-connection cap. The 120s bucket isolates connections cut at the
# Envoy/Contour response_timeout boundary from genuinely long-lived ones.
STREAM_CONNECTION_DURATION_BUCKETS = [
    1.0,
    5.0,
    15.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    960.0,
    1_800.0,
    3_600.0,
    7_200.0,
    21_600.0,
]
# Stream length is capped at TASK_RUN_STREAM_MAX_LENGTH (~5k); the top buckets
# show how close real runs get to the trim threshold.
STREAM_LENGTH_BUCKETS = [10.0, 50.0, 100.0, 500.0, 1_000.0, 2_500.0, 5_000.0, 10_000.0, 15_000.0, 20_000.0]


TASK_RUN_STREAM_CONNECTIONS_OPENED_TOTAL = Counter(
    "posthog_tasks_task_run_stream_connections_opened_total",
    "SSE task-run stream connections opened",
    labelnames=["origin_product"],
)

TASK_RUN_STREAM_CONNECTIONS_CLOSED_TOTAL = Counter(
    "posthog_tasks_task_run_stream_connections_closed_total",
    "SSE task-run stream connections closed, labeled by how they ended",
    labelnames=["origin_product", "outcome"],
)

TASK_RUN_STREAM_CONNECTION_DURATION_SECONDS = Histogram(
    "posthog_tasks_task_run_stream_connection_duration_seconds",
    "Lifetime of an SSE task-run stream connection",
    labelnames=["origin_product", "outcome"],
    buckets=STREAM_CONNECTION_DURATION_BUCKETS,
)

TASK_RUN_STREAM_LENGTH_ON_CONNECT = Histogram(
    "posthog_tasks_task_run_stream_length_on_connect",
    "Redis stream length observed when an SSE connection reconnects with a cursor",
    buckets=STREAM_LENGTH_BUCKETS,
)

TASK_RUN_STREAM_RESUME_GAP_TOTAL = Counter(
    "posthog_tasks_task_run_stream_resume_gap_total",
    "SSE reconnects whose Last-Event-ID was already trimmed from Redis (events lost for that client)",
    labelnames=["origin_product"],
)

TASK_RUN_AGENT_FAILURE_TOTAL = Counter(
    "posthog_tasks_agent_turn_failed_total",
    "TaskRun transitions to FAILED via the API facade (agent-server turn failures)",
    labelnames=["origin_product", "mode", "run_source", "task_runtime", "runtime_adapter"],
)

TASK_RUN_FOLLOWUP_DELIVERY_FAILED_TOTAL = Counter(
    "posthog_tasks_followup_delivery_failed_total",
    "Follow-up user message deliveries to a live sandbox that failed",
    labelnames=["origin_product", "retryable"],
)

SANDBOX_DEADLINE_BUCKETS = [5.0, 15.0, 30.0, 60.0, 120.0, 180.0, 300.0, 600.0]

SANDBOX_DEADLINE_TOTAL = Counter(
    "posthog_tasks_sandbox_deadline_total",
    "Interactive cloud runs that reached the pre-deadline lead time on their sandbox, "
    "by what the run ended up on. rotated moved onto a replacement sandbox; snapshot_only "
    "kept the sandbox it had and saved the session; snapshot_failed kept it with nothing "
    "saved; routing_lost backed out of a rotation and could not repoint the run, so it can "
    "take no more messages.",
    labelnames=["outcome", "reason", "origin_product"],
)

SANDBOX_ROTATION_DURATION_SECONDS = Histogram(
    "posthog_tasks_sandbox_rotation_duration_seconds",
    "Wall time a run spent handling its sandbox deadline. The run answers no messages for "
    "this long, so it is the user-visible cost of a rotation.",
    labelnames=["outcome"],
    buckets=SANDBOX_DEADLINE_BUCKETS,
)

FOLLOWUP_SANDBOX_STOPPED_TOTAL = Counter(
    "posthog_tasks_followup_sandbox_stopped_total",
    "Follow-up deliveries rejected because the control plane reports the run's sandbox "
    "stopped, by where the check caught it",
    labelnames=["origin_product", "detected_by"],
)

FOLLOWUP_DENIED_PERMISSION_STOP_TOTAL = Counter(
    "posthog_tasks_followup_denied_permission_stop_total",
    "Follow-up deliveries dropped instead of retried because the turn ended on a permission "
    "the actor denied. A retry would re-ask the refused question.",
    labelnames=["origin_product"],
)

TASK_RUN_WIZARD_UNBOUND_TOTAL = Counter(
    "posthog_tasks_wizard_run_unbound_total",
    "Wizard cloud runs that reached a terminal status without an output.pr_url binding",
    labelnames=["status"],
)

PUSH_DISPATCHER_FAILURES_TOTAL = Counter(
    "posthog_tasks_push_dispatcher_failures_total",
    "Push-notification dispatch attempts that failed and were swallowed by the best-effort dispatcher",
    labelnames=["kind", "reason"],
)

PUSH_DISPATCHER_OUTCOMES_TOTAL = Counter(
    "posthog_tasks_push_dispatcher_outcomes_total",
    "Push-notification dispatcher decisions before the Celery delivery task",
    labelnames=["kind", "outcome"],
)

# reason is one of: created, deduped, overlap_skipped, rate_capped, disabled, gate_blocked
# (LoopFireResult.reason), a fixed, code-defined set, safe as a label.
LOOP_FIRE_TOTAL = Counter(
    "posthog_tasks_loop_fire_total",
    "Loop trigger fire outcomes",
    labelnames=["reason"],
)

LOOP_AUTO_PAUSED_TOTAL = Counter(
    "posthog_tasks_loop_auto_paused_total",
    "Loops auto-paused after exceeding the consecutive-failure threshold",
)

CodeUsageGateOutcome = Literal["checked_allowed", "checked_blocked", "fail_open", "org_deactivated"]
ComputeQuotaOutcome = Literal["checked_allowed", "checked_blocked", "fail_open"]
DesktopAccessOutcome = Literal[
    "allowed",
    "legacy_allowed",
    "legacy_denied",
    "startup_plan",
    "prepaid_credits",
    "override",
    "resolution_failure",
]

# outcome: checked_allowed/checked_blocked when the LLM gateway answered the usage check,
# fail_open when a gateway/token error let the run proceed unchecked (see LOOPS.md Security:
# a degraded gateway must not silently remove the only cost backstop), org_deactivated when
# the local deactivated-organization check blocked the run before any gateway call.
CODE_USAGE_GATE_CHECK_TOTAL = Counter(
    "posthog_tasks_code_usage_gate_check_total",
    "Cloud usage-gate check outcomes for PostHog Code runs",
    labelnames=["outcome"],
)

COMPUTE_QUOTA_CHECK_TOTAL = Counter(
    "posthog_tasks_compute_quota_check_total",
    "Compute quota-check outcomes for billable PostHog Desktop runs",
    labelnames=["outcome"],
)

DESKTOP_ACCESS_DECISIONS_TOTAL = Counter(
    "posthog_tasks_desktop_access_decisions_total",
    "PostHog Desktop access decisions by bounded outcome",
    labelnames=["outcome"],
)


def observe_compute_quota_check(outcome: ComputeQuotaOutcome) -> None:
    COMPUTE_QUOTA_CHECK_TOTAL.labels(outcome=outcome).inc()


# analytics_event: pr_created | pr_merged | pr_closed | pr_reviewed (bounded, code-defined).
# reason: unresolved_installation (no Integration matched the delivery's installation id) or
#         capture_exception (posthoganalytics.capture raised). Both paths were silent before,
#         so a webhook-side event loss only showed up as a capture-rate dip in analytics.
GITHUB_WEBHOOK_PR_EVENT_DROPPED_TOTAL = Counter(
    "posthog_tasks_github_webhook_pr_event_dropped_total",
    "GitHub PR webhook events that never reached PostHog capture, labeled by event and drop reason",
    labelnames=["analytics_event", "reason"],
)

# outcome: resolved | unresolved | timeout | error. timeout means the bounded org-member
# lookup hit statement_timeout and was skipped so the delivery survives without attribution.
GITHUB_WEBHOOK_ATTRIBUTION_TOTAL = Counter(
    "posthog_tasks_github_webhook_attribution_total",
    "Outcome of the org-member lookup that attributes a GitHub login on the pr_merged/pr_reviewed webhook path",
    labelnames=["outcome"],
)

# scoped: "true" when the delivery's installation resolved to at least one team, so the
# TaskRun lookup could ride the team_id index. "false" means it fell back to the legacy
# unscoped lookup, which walks posthog_task_run once per leg — the thing we want to watch
# shrink in production before considering anything stricter.
GITHUB_WEBHOOK_TASK_RUN_LOOKUP_TOTAL = Counter(
    "posthog_tasks_github_webhook_task_run_lookup_total",
    "GitHub webhook TaskRun lookups, labeled by whether they were scoped to the installation's teams",
    labelnames=["scoped"],
)

GitHubWebhookAnalyticsEvent = Literal["pr_created", "pr_merged", "pr_closed", "pr_reviewed"]
GitHubWebhookDropReason = Literal["unresolved_installation", "capture_exception"]
GitHubWebhookAttributionOutcome = Literal["resolved", "unresolved", "timeout", "error"]


def observe_github_webhook_pr_event_dropped(
    *, analytics_event: GitHubWebhookAnalyticsEvent, reason: GitHubWebhookDropReason
) -> None:
    GITHUB_WEBHOOK_PR_EVENT_DROPPED_TOTAL.labels(analytics_event=analytics_event, reason=reason).inc()


def observe_github_webhook_attribution(*, outcome: GitHubWebhookAttributionOutcome) -> None:
    GITHUB_WEBHOOK_ATTRIBUTION_TOTAL.labels(outcome=outcome).inc()


def observe_github_webhook_task_run_lookup(*, scoped: bool) -> None:
    GITHUB_WEBHOOK_TASK_RUN_LOOKUP_TOTAL.labels(scoped="true" if scoped else "false").inc()


def _metric_label(value: object | None) -> str:
    if value is None:
        return "unknown"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _bounded_metric_label(value: object | None, allowed_values: set[str]) -> str:
    label = _metric_label(value)
    if label == "unknown" or label in allowed_values:
        return label
    return "other"


def _failure_metric_label(value: object | None) -> str:
    label = _metric_label(value)
    if label == "unknown":
        return label
    return label[:100]


def _task_runtime_label(task_run: "TaskRun | None") -> str:
    if task_run is None:
        return "unknown"
    return _bounded_metric_label(getattr(task_run.task, "runtime", None), _ALLOWED_TASK_RUNTIMES)


def _effective_runtime_adapter_label(task_run: "TaskRun | None", state: dict) -> str:
    task_runtime = _task_runtime_label(task_run)
    if task_runtime == "pi":
        return "pi"

    configured_adapter = state.get("runtime_adapter")
    if configured_adapter is not None:
        return _bounded_metric_label(configured_adapter, _ALLOWED_RUNTIME_ADAPTERS)

    # ACP's default harness is Claude. A model-only override deliberately leaves
    # runtime_adapter unset, so treating that valid configuration as unknown hides
    # the runtime that actually handled the run.
    return "claude" if task_runtime == "acp" else "unknown"


def _task_run_labels(task_run: "TaskRun | None") -> dict[str, str]:
    if task_run is None:
        return {
            "origin_product": "unknown",
            "run_environment": "unknown",
            "mode": "unknown",
            "run_source": "unknown",
            "task_runtime": "unknown",
            "runtime_adapter": "unknown",
            "prewarmed": "unknown",
        }

    state = task_run.state if isinstance(task_run.state, dict) else {}
    return {
        "origin_product": origin_product_label(task_run),
        "run_environment": _metric_label(task_run.environment),
        "mode": _bounded_metric_label(state.get("mode"), _ALLOWED_MODES),
        "run_source": _bounded_metric_label(state.get("run_source"), _ALLOWED_RUN_SOURCES),
        "task_runtime": _task_runtime_label(task_run),
        "runtime_adapter": _effective_runtime_adapter_label(task_run, state),
        "prewarmed": "true" if state.get("prewarmed") else "false",
    }


def observe_task_run_created(task_run: "TaskRun") -> None:
    TASK_RUN_CREATED_TOTAL.labels(**_task_run_labels(task_run)).inc()


def observe_task_run_dispatch_callback(task_run: "TaskRun | None", *, phase: Literal["scheduled", "fired"]) -> None:
    TASK_RUN_DISPATCH_CALLBACK_TOTAL.labels(**_task_run_labels(task_run), phase=phase).inc()


def observe_task_run_workflow_start(
    task_run: "TaskRun | None",
    *,
    outcome: TaskWorkflowStartOutcome,
    reason: str,
) -> None:
    TASK_RUN_WORKFLOW_START_TOTAL.labels(
        **_task_run_labels(task_run),
        outcome=outcome,
        reason=reason,
    ).inc()


def observe_prewarmed_activated(task_run: "TaskRun") -> None:
    PREWARMED_ACTIVATED_TOTAL.labels(origin_product=origin_product_label(task_run)).inc()


def observe_custom_image_build(outcome: CustomImageBuildOutcome) -> None:
    try:
        CUSTOM_IMAGE_BUILD_TOTAL.labels(outcome=outcome).inc()
    except Exception:
        logger.exception("custom_image_build_metric_failed", outcome=outcome)


def observe_dev_stack_image_bake(outcome: DevStackImageBakeOutcome, *, trigger: str) -> None:
    try:
        from posthog.utils import get_instance_region  # noqa: PLC0415

        DEV_STACK_IMAGE_BAKE_TOTAL.labels(
            outcome=outcome,
            region=get_instance_region() or "unknown",
            trigger=trigger,
        ).inc()
    except Exception:
        logger.exception("dev_stack_image_bake_metric_failed", outcome=outcome, trigger=trigger)


def origin_product_label(task_run: "TaskRun | None") -> str:
    """Bounded origin_product metric label resolved from the task run's task."""
    if task_run is None:
        return "unknown"
    return _metric_label(getattr(task_run.task, "origin_product", None))


def observe_stream_connection_opened(origin_product: str) -> None:
    TASK_RUN_STREAM_CONNECTIONS_OPENED_TOTAL.labels(origin_product=origin_product).inc()


def observe_stream_connection_closed(
    origin_product: str, outcome: StreamConnectionOutcome, duration_seconds: float
) -> None:
    TASK_RUN_STREAM_CONNECTIONS_CLOSED_TOTAL.labels(origin_product=origin_product, outcome=outcome).inc()
    TASK_RUN_STREAM_CONNECTION_DURATION_SECONDS.labels(origin_product=origin_product, outcome=outcome).observe(
        duration_seconds
    )


def observe_stream_length_on_connect(length: int) -> None:
    TASK_RUN_STREAM_LENGTH_ON_CONNECT.observe(length)


def observe_stream_resume_gap(origin_product: str) -> None:
    TASK_RUN_STREAM_RESUME_GAP_TOTAL.labels(origin_product=origin_product).inc()


def observe_task_run_failed(properties: dict[str, object]) -> None:
    TASK_RUN_FAILED_TOTAL.labels(
        origin_product=_metric_label(properties.get("origin_product")),
        mode=_bounded_metric_label(properties.get("mode"), _ALLOWED_MODES),
        run_source=_bounded_metric_label(properties.get("run_source"), _ALLOWED_RUN_SOURCES),
        runtime_adapter=_bounded_metric_label(properties.get("runtime_adapter"), _ALLOWED_RUNTIME_ADAPTERS),
        error_type=_failure_metric_label(properties.get("error_type")),
        temporal_activity_type=_failure_metric_label(properties.get("temporal_activity_type")),
        temporal_activity_retry_state=_failure_metric_label(properties.get("temporal_activity_retry_state")),
        cause_error_type=_failure_metric_label(properties.get("cause_error_type")),
    ).inc()


def observe_agent_turn_failed(task_run: "TaskRun") -> None:
    labels = _task_run_labels(task_run)
    TASK_RUN_AGENT_FAILURE_TOTAL.labels(
        origin_product=labels["origin_product"],
        mode=labels["mode"],
        run_source=labels["run_source"],
        task_runtime=labels["task_runtime"],
        runtime_adapter=labels["runtime_adapter"],
    ).inc()


_WIZARD_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def observe_wizard_run_unbound(task_run: "TaskRun") -> None:
    """Record a wizard run ending without its PR ever binding.

    Safe to call on any status write; only terminal wizard runs without an
    output.pr_url count. Every binding failure mode is silent (agent used a
    different branch, webhook undelivered, write swallowed), so this counter
    is the only signal that the wizard PR pipeline regressed.
    """
    if task_run.status not in _WIZARD_TERMINAL_STATUSES:
        return
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if not state.get("wizard_head_branch"):
        return
    output = task_run.output if isinstance(task_run.output, dict) else {}
    if output.get("pr_url"):
        return
    TASK_RUN_WIZARD_UNBOUND_TOTAL.labels(status=task_run.status).inc()
    logger.warning(
        "wizard_run_terminal_without_pr",
        run_id=str(task_run.id),
        status=task_run.status,
        wizard_head_branch=state.get("wizard_head_branch"),
    )


def observe_followup_delivery_failed(task_run: "TaskRun", *, retryable: bool) -> None:
    TASK_RUN_FOLLOWUP_DELIVERY_FAILED_TOTAL.labels(
        origin_product=origin_product_label(task_run),
        retryable="true" if retryable else "false",
    ).inc()


_SANDBOX_DEADLINE_OUTCOMES = {"rotated", "snapshot_only", "snapshot_failed", "routing_lost"}
_SANDBOX_DEADLINE_REASONS = {
    "none",
    "no_sandbox",
    "flag_disabled",
    "agent_active",
    "followup_in_flight",
    "run_completed",
    "snapshot_missing",
    "provision_failed",
    "snapshot_unused",
}


def observe_sandbox_deadline(properties: dict[str, object]) -> None:
    outcome = _bounded_metric_label(properties.get("outcome"), _SANDBOX_DEADLINE_OUTCOMES)
    SANDBOX_DEADLINE_TOTAL.labels(
        outcome=outcome,
        reason=_bounded_metric_label(properties.get("reason"), _SANDBOX_DEADLINE_REASONS),
        origin_product=_metric_label(properties.get("origin_product")),
    ).inc()
    duration = properties.get("duration_seconds")
    if isinstance(duration, int | float) and not isinstance(duration, bool):
        SANDBOX_ROTATION_DURATION_SECONDS.labels(outcome=outcome).observe(float(duration))


def observe_followup_sandbox_stopped(task_run: "TaskRun | None", *, detected_by: str) -> None:
    FOLLOWUP_SANDBOX_STOPPED_TOTAL.labels(
        origin_product=origin_product_label(task_run),
        detected_by=detected_by,
    ).inc()


def observe_followup_denied_permission_stop(task_run: "TaskRun | None") -> None:
    FOLLOWUP_DENIED_PERMISSION_STOP_TOTAL.labels(origin_product=origin_product_label(task_run)).inc()


def observe_loop_fire(*, reason: str) -> None:
    LOOP_FIRE_TOTAL.labels(reason=reason).inc()


def observe_loop_auto_paused() -> None:
    LOOP_AUTO_PAUSED_TOTAL.inc()


def observe_code_usage_gate_check(*, outcome: CodeUsageGateOutcome) -> None:
    CODE_USAGE_GATE_CHECK_TOTAL.labels(outcome=outcome).inc()


def observe_desktop_access_decision(*, outcome: DesktopAccessOutcome) -> None:
    DESKTOP_ACCESS_DECISIONS_TOTAL.labels(outcome=outcome).inc()
