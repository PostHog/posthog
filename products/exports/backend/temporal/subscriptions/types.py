import uuid
import typing
import dataclasses

from posthog.slo.types import SloConfig

# Type names of these failures never appear in recipient-facing copy. When a safe code and message
# exist, they are available to query-access owners; this mask only governs the legacy fallback that
# has no persisted details. The type still lands in diagnostics, logs, and error tracking.
UNDISCLOSED_QUERY_ERROR_TYPES = frozenset({"ClickHouseQueryMemoryLimitExceeded"})


class QueryErrorDetails(typing.TypedDict):
    """A failed query's type paired with its optional safe code and message."""

    type: typing.Optional[str]
    code: typing.Optional[str]
    message: typing.Optional[str]


def safe_query_error_details(exc: BaseException) -> typing.Optional[QueryErrorDetails]:
    """Return stable details for an explicitly safe query exception in a wrapped exception chain."""
    seen: set[int] = set()
    current: typing.Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if getattr(type(current), "is_user_safe", False) is True:
            code = getattr(current, "code_name", None)
            if not isinstance(code, str):
                get_codes = getattr(current, "get_codes", None)
                code = get_codes() if callable(get_codes) else None

            raw_detail = getattr(current, "detail", None)
            message = str(raw_detail) if isinstance(raw_detail, str) else str(current)
            if isinstance(code, str) and message:
                return {
                    "type": type(current).__name__,
                    "code": code,
                    "message": message.replace("\x00", ""),
                }
        seen.add(id(current))
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return None


def safe_error_message(exc: BaseException) -> typing.Optional[str]:
    """Owner-safe snippet of a query exception, or None when its text may carry team-scoped data.

    Uses the single classifier above so every consumer shares the same allowlist, wrapped-chain
    handling, and NUL stripping. Everything else returns None and callers use a generic fallback.
    """
    details = safe_query_error_details(exc)
    return details["message"] if details else None


class DeliveryStatus:
    """Mirrors SubscriptionDelivery.Status choices for use in Temporal workflows.

    Plain string constants (not enum.Enum) for the same Temporal serialization
    reason as SubscriptionTriggerType.
    """

    STARTING = "starting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExportAssetPreparationStatus:
    READY = "ready"
    NO_EXPORTABLE_INSIGHTS = "no_exportable_insights"


class NoExportableInsightsReason:
    DASHBOARD_DELETED = "dashboard_deleted"
    EMPTY_DASHBOARD = "empty_dashboard"
    MISSING_RESOURCE = "missing_resource"
    SELECTED_INSIGHTS_NO_LONGER_AVAILABLE = "selected_insights_no_longer_available"


class NoExportableInsightsContext(typing.TypedDict):
    reason: str
    resource_type: str
    available_insight_count: int
    selected_insight_count: int


class NoExportableInsightsErrorDetails(NoExportableInsightsContext):
    message: str
    type: str


# Mirrors Subscription.ResourceType.AI_PROMPT — a plain constant so the Temporal
# workflow sandbox can route by resource type without importing the Django model.
AI_PROMPT_RESOURCE_TYPE = "ai_prompt"

# `SubscriptionDelivery.content_snapshot` keys for the AI report. The markdown and prompt can
# exceed Temporal's ~2 MiB payload cap, so they travel through Postgres by reference rather than
# on the wire (the same pattern insight snapshots use). They live alongside the workflow types so
# the API serializer can import them without pulling in the LLM delivery stack.
AI_REPORT_SNAPSHOT_KEY = "ai_report"
# The prompt that generated the report, captured at generation time so the delivery is reproducible.
AI_REPORT_PROMPT_SNAPSHOT_KEY = "ai_report_prompt"
# Per-step query diagnostics (generated HogQL + failure type) so a degraded report is debuggable
# after the fact. Written alongside the markdown; never shipped to recipients.
AI_REPORT_DIAGNOSTICS_KEY = "ai_report_diagnostics"
# Top-level delivery error type for a report whose generated queries all failed. Shared with the
# serializer's query-access scrub so a rename cannot accidentally expose query-derived details.
AI_REPORT_QUERY_FAILURE_TYPE = "AIReportQueryFailure"
# The analysis window's end for this run, as a UTC ISO instant. The next run anchors its window here
# (exactly gap-free); rows written before this key existed fall back to finished_at.
AI_REPORT_WINDOW_END_KEY = "ai_report_window_end"
AI_REPORT_CHARTS_KEY = "ai_report_charts"


class SubscriptionTriggerType:
    """How a subscription delivery was triggered.

    Plain string constants (not enum.Enum) because Temporal's
    DefaultPayloadConverter mis-deserializes str enums as character lists.
    """

    SCHEDULED = "scheduled"  # Regular cron-based delivery
    SUBSCRIPTION_CHANGE = "target_change"  # An API create or edit triggered an immediate delivery.
    MANUAL = "manual"  # User clicked "Test delivery"


@dataclasses.dataclass
class DueSubscription:
    subscription_id: int
    team_id: int
    distinct_id: str
    next_delivery_date: typing.Optional[str] = None
    # Lets the scheduler fan out AI-prompt subscriptions to ProcessAISubscriptionWorkflow
    # and everything else to ProcessSubscriptionWorkflow.
    resource_type: str = ""


@dataclasses.dataclass
class FetchDueSubscriptionsActivityInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@dataclasses.dataclass
class CreateExportAssetsInputs:
    subscription_id: int
    max_asset_count: int | None = None
    # TODO(2026-07-30): Remove in a follow-up after this PR is fully deployed and pre-deployment activity payloads expire.
    previous_value: typing.Optional[str] = None
    # When set, the activity persists the per-insight snapshot directly onto
    # SubscriptionDelivery.content_snapshot. Keeps multi-MB query_results off
    # the Temporal payload wire (~2 MiB gRPC cap). Unset for standalone callers
    # (tests, management commands) that have no delivery row to write to.
    delivery_id: typing.Optional[uuid.UUID] = None


@dataclasses.dataclass
class CreateExportAssetsResult:
    """Small metadata envelope for create_export_assets.

    Multi-MB snapshot data is written to Postgres from inside the activity via
    `delivery_id`, not returned here — the activity return payload crosses
    Temporal's ~2 MiB gRPC boundary and must stay size-bounded by construction.
    """

    exported_asset_ids: list[int]
    total_insight_count: int
    team_id: int = 0
    distinct_id: str = ""
    target_type: str = ""
    available_insight_count: int = 0
    selected_insight_count: int = 0
    status: str = ExportAssetPreparationStatus.READY
    failure_context: NoExportableInsightsContext | None = None


@dataclasses.dataclass
class DeliverSubscriptionInputs:
    subscription_id: int
    exported_asset_ids: list[int]
    total_insight_count: int
    previous_target_value: typing.Optional[str] = None
    # TODO(2026-07-30): Remove these legacy keys in a follow-up after this PR is fully deployed and pre-deployment activity payloads expire.
    previous_value: typing.Optional[str] = None
    is_new_subscription_target: bool | None = None
    invite_message: typing.Optional[str] = None
    change_summary: typing.Optional[str] = None
    summary_skipped_over_budget: bool = False
    # The delivery row to write outcomes onto. AI deliveries also read the generated
    # report markdown back from it (kept off the Temporal wire, ~2 MiB cap).
    delivery_id: typing.Optional[uuid.UUID] = None


@dataclasses.dataclass
class ProcessSubscriptionWorkflowInputs:
    subscription_id: int
    team_id: int = 0
    distinct_id: str = ""
    previous_target_value: typing.Optional[str] = None
    # TODO(2026-07-30): Remove in a follow-up after this PR is fully deployed and pre-deployment workflow payloads expire.
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    trigger_type: str = SubscriptionTriggerType.SUBSCRIPTION_CHANGE
    scheduled_at: typing.Optional[str] = None
    # Lets HandleSubscriptionValueChangeWorkflow route AI-prompt subs to
    # ProcessAISubscriptionWorkflow. Passed by the API from the loaded instance.
    resource_type: str = ""


@dataclasses.dataclass
class TrackedSubscriptionInputs:
    """Internal inputs for ProcessSubscriptionWorkflow with SLO tracking.

    Duplicates ProcessSubscriptionWorkflowInputs fields intentionally:
    Temporal deserializes by the declared parameter type, so SLO config
    must be on the type the workflow declares. Due to this "extending"
    ProcessSubscriptionWorkflow did not work.
    """

    subscription_id: int
    team_id: int = 0
    distinct_id: str = ""
    previous_target_value: typing.Optional[str] = None
    # TODO(2026-07-30): Remove in a follow-up after this PR is fully deployed and pre-deployment workflow payloads expire.
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    slo: SloConfig | None = None
    trigger_type: str = SubscriptionTriggerType.SUBSCRIPTION_CHANGE
    scheduled_at: typing.Optional[str] = None
    resource_type: str = ""


RecipientResultStatus = typing.Literal["success", "failed", "partial"]


@dataclasses.dataclass
class RecipientResult:
    recipient: str
    status: RecipientResultStatus
    error: typing.Optional[dict[str, str]] = None  # {"message": str, "type": str}
    # Owner-safe failure reason; None when the raw error may carry team-scoped/internal detail.
    # The UI renders this (or a generic fallback), never error.message.
    human_readable_error: typing.Optional[str] = None


@dataclasses.dataclass
class DeliverSubscriptionResult:
    recipient_results: list[RecipientResult] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class GenerateAIReportInputs:
    subscription_id: int
    # The report markdown is written onto this SubscriptionDelivery row rather than
    # returned on the wire — it can exceed Temporal's ~2 MiB payload cap.
    delivery_id: uuid.UUID


@dataclasses.dataclass(frozen=False)
class GenerateAIReportResult:
    """Outcome of the generation phase. `aborted` signals a terminal pre-delivery
    failure (consent revoked, prompt invalid) that already auto-disabled the
    subscription; the workflow records `recipient_results` as FAILED and skips delivery.
    `skipped` signals an over-AI-credit-budget skip: generation rescheduled the sub past
    the credit reset and notified the owner — the workflow records SKIPPED (not FAILED,
    the sub isn't broken) and skips delivery.

    The query-failure counts let the workflow flag a fully-degraded report (every query failed →
    FAILED, not COMPLETED) without re-reading the per-query detail from content_snapshot."""

    aborted: bool = False
    skipped: bool = False
    recipient_results: list[RecipientResult] = dataclasses.field(default_factory=list)
    failed_step_count: int = 0
    total_step_count: int = 0
    # Kept for Temporal histories written before query_errors existed. New results derive it in
    # __post_init__ so callers only provide the richer representation.
    query_error_types: list[str] = dataclasses.field(default_factory=list)
    target_type: str = ""
    # Appended to preserve the positional shape of this Temporal activity result.
    query_errors: list[QueryErrorDetails] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.query_error_types and self.query_errors:
            self.query_error_types = sorted({error["type"] for error in self.query_errors if error["type"]})

    @property
    def all_queries_failed(self) -> bool:
        # Single source of truth for the "fully degraded" judgement, so callers don't re-derive it.
        return bool(self.total_step_count) and self.failed_step_count >= self.total_step_count

    def failure_error(self) -> dict[str, typing.Any]:
        all_error_types = set(self.query_error_types)
        all_error_types.update(error["type"] for error in self.query_errors if error["type"])
        disclosed_types = sorted(t for t in all_error_types if t not in UNDISCLOSED_QUERY_ERROR_TYPES)
        detail = f" ({', '.join(disclosed_types)})" if disclosed_types else ""
        subject = (
            "The query the AI generated"
            if self.total_step_count == 1
            else f"All {self.total_step_count} queries the AI generated"
        )
        error: dict[str, typing.Any] = {
            "message": f"{subject} failed to run{detail}, so the report could not be computed.",
            "type": AI_REPORT_QUERY_FAILURE_TYPE,
        }

        safe_errors: list[dict[str, str]] = []
        for query_error in self.query_errors:
            error_type = query_error["type"]
            code = query_error["code"]
            message = query_error["message"]
            if error_type and code and message:
                safe_errors.append({"type": error_type, "code": code, "message": message})
        if safe_errors:
            error["code"] = safe_errors[0]["code"]
            error["details"] = safe_errors
        return error

    def delivered_status(self) -> tuple[str, typing.Optional[dict[str, typing.Any]]]:
        # Status to record once the report shipped: a fully-degraded report (every query failed) is FAILED
        # with its failure detail — recording it COMPLETED would misrepresent an empty report. Partial
        # failures stay COMPLETED. Owns this mapping so the workflow can't diverge from the judgement above.
        if self.all_queries_failed:
            return DeliveryStatus.FAILED, self.failure_error()
        return DeliveryStatus.COMPLETED, None


@dataclasses.dataclass
class DeliveryAbort:
    """Returned by `validate_subscription_for_delivery` when the workflow should abort.
    `failed_recipient` is populated only when this run auto-disabled the sub
    (workflow records FAILED). None means already-disabled — idempotency redispatch."""

    failed_recipient: typing.Optional[RecipientResult] = None


@dataclasses.dataclass
class CreateDeliveryRecordInputs:
    subscription_id: int
    team_id: int
    trigger_type: str
    temporal_workflow_id: str
    idempotency_key: str
    scheduled_at: typing.Optional[str] = None


@dataclasses.dataclass
class UpdateDeliveryRecordInputs:
    """Patch a SubscriptionDelivery row. None on optional collections means leave the column unchanged.

    Per-insight query results are written to Postgres directly from
    `create_export_assets` rather than shipping them back through this input
    (they can easily exceed Temporal's ~2 MiB payload cap).
    """

    delivery_id: uuid.UUID
    status: str
    exported_asset_ids: typing.Optional[list[int]] = None
    recipient_results: typing.Optional[list[dict[str, typing.Any]]] = None
    error: typing.Optional[dict[str, typing.Any] | NoExportableInsightsErrorDetails] = None
    change_summary: typing.Optional[str] = None
    finished: bool = False


@dataclasses.dataclass
class SnapshotInsightsInputs:
    subscription_id: int
    team_id: int
    delivery_id: typing.Optional[str] = None
    summary_enabled: bool = False
    exported_asset_ids: typing.Optional[list[int]] = None


@dataclasses.dataclass
class SnapshotInsightsResult:
    summary_text: str | None = None
    # Set only on the over-budget skip — drives the user-facing notice in the report.
    summary_skipped_over_budget: bool = False


@dataclasses.dataclass
class ScheduleAllSubscriptionsWorkflowInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }
