import json
import uuid
import asyncio
import datetime as dt
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    find_temporal_timeout_error,
    resolve_error_trace,
    resolve_exception_class,
    truncate_for_temporal_payload,
    unwrap_temporal_cause,
)
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import (
    ExportAssetActivityInputs,
    ExportAssetResult,
    ExportError,
    extract_error_details,
    is_user_query_export_error,
)

from products.exports.backend.tasks.failure_handler import (
    SLO_FAILURE_CATEGORY_ACTIVITY_TIMEOUT,
    SLO_FAILURE_COMPONENT_EXPORT_WORKER,
)
from products.exports.backend.temporal.subscriptions.activities import (
    SUBSCRIPTION_RECOVERY_ACTIVITY_TIMEOUT,
    advance_next_delivery_date,
    advance_next_delivery_date_v2,
    advance_subscription_scheduler_cursor_activity,
    complete_subscription_scheduler_claim_activity,
    confirm_subscription_scheduler_claim_activity,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    deliver_subscription_v2,
    fetch_claimed_due_subscriptions_activity,
    fetch_due_subscriptions_activity,
    notify_subscription_delivery_failure,
    recover_subscription_scheduler_claims_activity,
    release_subscription_scheduler_claim_activity,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.retry_policy import (
    SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT,
    SUBSCRIPTION_DELIVER_RETRY_POLICY,
    SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
    SUBSCRIPTION_VALIDATE_RETRY_POLICY,
)
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import (
    AI_PROMPT_RESOURCE_TYPE,
    SUBSCRIPTION_CLAIM_LEASE_SAFETY_MARGIN,
    SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT,
    AdvanceNextDeliveryDateInputs,
    AdvanceSubscriptionSchedulerCursorInputs,
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    DeliveryStatus,
    DueSubscription,
    ExportAssetPreparationStatus,
    FetchDueSubscriptionsActivityInputs,
    GenerateAIReportInputs,
    NoExportableInsightsErrorDetails,
    ProcessSubscriptionWorkflowInputs,
    RecipientResult,
    RecoverSubscriptionSchedulerClaimsInputs,
    ScheduleAllSubscriptionsWorkflowInputs,
    SnapshotInsightsInputs,
    SubscriptionSchedulerClaimInputs,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
    UpdateDeliveryRecordInputs,
)


class SubscriptionFailureStage(StrEnum):
    DELIVERY_RECORD = "delivery_record"
    VALIDATION = "validation"
    ASSET_PREPARATION = "asset_preparation"
    ASSET_GENERATION = "asset_generation"
    REPORT_GENERATION = "report_generation"
    DELIVERY = "delivery"
    RECORD_UPDATE = "record_update"
    SCHEDULE_UPDATE = "schedule_update"


_FAILURE_STAGE_COMPONENT: dict[SubscriptionFailureStage, str] = {
    SubscriptionFailureStage.DELIVERY_RECORD: "delivery_record",
    SubscriptionFailureStage.VALIDATION: "subscription_validation",
    SubscriptionFailureStage.ASSET_PREPARATION: "export_preparation",
    SubscriptionFailureStage.ASSET_GENERATION: SLO_FAILURE_COMPONENT_EXPORT_WORKER,
    SubscriptionFailureStage.REPORT_GENERATION: "ai_report_generation",
    SubscriptionFailureStage.DELIVERY: "subscription_delivery",
    SubscriptionFailureStage.RECORD_UPDATE: "delivery_record",
    SubscriptionFailureStage.SCHEDULE_UPDATE: "subscription_schedule",
}


@frozen
class _ScheduledSubscriptionChild:
    workflow: Callable[..., Coroutine[Any, Any, None]]
    inputs: TrackedSubscriptionInputs
    workflow_id: str


def _to_recipient_dicts(recipient_results: list[RecipientResult]) -> list[dict]:
    return [
        {
            "recipient": r.recipient,
            "status": r.status,
            **({"error": r.error} if r.error else {}),
            **({"human_readable_error": r.human_readable_error} if r.human_readable_error else {}),
        }
        for r in recipient_results
    ]


def _build_outcome_assets(
    asset_ids: list[int],
    export_results: list[ExportAssetResult | BaseException],
) -> tuple[list[ExportAssetResult], list[int]]:
    """Classify export results into outcome assets and collect successful asset IDs.

    BaseException objects from asyncio.gather(return_exceptions=True) aren't
    serializable across the Temporal activity boundary, so this classification
    must happen in the workflow, not in an activity.
    """
    outcome_assets: list[ExportAssetResult] = []
    successful_asset_ids: list[int] = []
    for asset_id, result in zip(asset_ids, export_results):
        if isinstance(result, BaseException):
            outcome_assets.append(
                ExportAssetResult(
                    exported_asset_id=asset_id,
                    success=False,
                    error=extract_error_details(result),
                )
            )
        else:
            outcome_assets.append(result)
            if result.success:
                successful_asset_ids.append(result.exported_asset_id)
    return outcome_assets, successful_asset_ids


def _summarize_export_failure_details(errors: list[ExportError]) -> dict[str, str | int | list[str]]:
    """Summarize per-asset failure dimensions onto one subscription SLO event."""

    details = [error.failure_details for error in errors if error.failure_details is not None]
    categories = sorted({detail["failure_category"] for detail in details})
    components = sorted({detail["failure_component"] for detail in details})
    retryable_failure_count = sum(detail["failure_retryable"] for detail in details)
    unclassified_failure_count = len(errors) - len(details)

    return {
        "failure_stage": SubscriptionFailureStage.ASSET_GENERATION.value,
        "failure_categories": categories,
        "failure_components": components,
        "failed_asset_count": len(errors),
        "failure_category_count": len(categories),
        "retryable_failed_asset_count": retryable_failure_count,
        "non_retryable_failed_asset_count": len(details) - retryable_failure_count,
        "unclassified_failed_asset_count": unclassified_failure_count,
    }


def _record_subscription_failure(
    slo: SloConfig | None,
    stage: SubscriptionFailureStage,
    exc: BaseException,
) -> None:
    if slo is None:
        return

    application_error = unwrap_temporal_cause(exc)
    if application_error is None and isinstance(exc, ApplicationError):
        application_error = exc
    timeout = find_temporal_timeout_error(exc)
    cause = application_error or timeout or exc

    slo.completion_properties.update(
        {
            "error_type": type(timeout).__name__ if timeout else resolve_exception_class(exc),
            "error_message": truncate_for_temporal_payload(str(cause), MAX_ERROR_MESSAGE_CHARS),
            "error_trace": resolve_error_trace(exc),
            "failure_stage": stage.value,
            "failure_category": SLO_FAILURE_CATEGORY_ACTIVITY_TIMEOUT if timeout else "activity_failure",
            "failure_component": _FAILURE_STAGE_COMPONENT[stage],
            "failure_retryable": True if timeout else bool(application_error and not application_error.non_retryable),
        }
    )


def _build_scheduled_subscription_child(
    subscription: DueSubscription,
    *,
    scheduler_claim_lease_expires_at: str | None = None,
) -> _ScheduledSubscriptionChild:
    tracked = TrackedSubscriptionInputs(
        subscription_id=subscription.subscription_id,
        team_id=subscription.team_id,
        distinct_id=subscription.distinct_id,
        trigger_type=SubscriptionTriggerType.SCHEDULED,
        scheduled_at=subscription.next_delivery_date,
        resource_type=subscription.resource_type,
        scheduler_claim_id=subscription.scheduler_claim_id,
        scheduler_claim_token=subscription.scheduler_claim_token,
        scheduler_claim_lease_expires_at=scheduler_claim_lease_expires_at,
        slo=SloConfig(
            operation=SloOperation.SUBSCRIPTION_DELIVERY,
            area=SloArea.ANALYTIC_PLATFORM,
            team_id=subscription.team_id,
            resource_id=str(subscription.subscription_id),
            distinct_id=subscription.distinct_id,
            start_properties={
                "resource_type": subscription.resource_type,
                "trigger_type": SubscriptionTriggerType.SCHEDULED,
            },
            completion_properties={
                "resource_type": subscription.resource_type,
                "trigger_type": SubscriptionTriggerType.SCHEDULED,
            },
        ),
    )
    workflow: Callable[..., Coroutine[Any, Any, None]]
    if subscription.resource_type == AI_PROMPT_RESOURCE_TYPE:
        workflow = ProcessAISubscriptionWorkflow.run
        child_id = f"process-ai-subscription-{subscription.subscription_id}"
    else:
        workflow = ProcessSubscriptionWorkflow.run
        child_id = f"process-subscription-{subscription.subscription_id}"
    return _ScheduledSubscriptionChild(workflow=workflow, inputs=tracked, workflow_id=child_id)


def _record_subscription_dispatch_outcome(region: str, outcome: str, count: int) -> None:
    if not count:
        return
    try:
        (
            temporalio.workflow.metric_meter()
            .with_additional_attributes(
                {
                    "scheduler": "subscriptions",
                    "region": region,
                    "outcome": outcome,
                }
            )
            .create_counter(
                "posthog_temporal_scheduler_child_start",
                "Subscription scheduler child-start outcomes.",
            )
            .add(count)
        )
    except Exception:
        temporalio.workflow.logger.exception("subscription_scheduler.dispatch_metric_failed")


async def _run_legacy_subscription_children(subscription_infos: list[DueSubscription]) -> None:
    tasks = []
    for subscription in subscription_infos:
        child = _build_scheduled_subscription_child(subscription)
        tasks.append(
            temporalio.workflow.execute_child_workflow(
                child.workflow,
                child.inputs,
                id=child.workflow_id,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT,
            )
        )

    if not tasks:
        return
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed_ids = []
    for subscription, result in zip(subscription_infos, results, strict=True):
        if isinstance(result, BaseException):
            if isinstance(result, WorkflowAlreadyStartedError):
                temporalio.workflow.logger.info(
                    "process_subscription.already_running",
                    extra={"subscription_id": subscription.subscription_id},
                )
            else:
                failed_ids.append(subscription.subscription_id)
                temporalio.workflow.logger.warning(
                    "process_subscription.child_workflow_error",
                    extra={"subscription_id": subscription.subscription_id, "error": str(result)},
                )

    if failed_ids:
        raise ApplicationError(
            f"Subscription deliveries failed for IDs: {failed_ids}",
            non_retryable=True,
        )


async def _start_claimed_subscription_children(subscription_infos: list[DueSubscription], region: str) -> None:
    unique_subscription_infos: list[DueSubscription] = []
    seen_occurrences: set[tuple[int, str | None]] = set()
    for subscription in subscription_infos:
        occurrence = (subscription.subscription_id, subscription.next_delivery_date)
        if occurrence in seen_occurrences:
            temporalio.workflow.logger.warning(
                "subscription_scheduler.duplicate_occurrence_ignored",
                extra={
                    "subscription_id": subscription.subscription_id,
                    "next_delivery_date": subscription.next_delivery_date,
                },
            )
            continue
        seen_occurrences.add(occurrence)
        unique_subscription_infos.append(subscription)

    async def start_one(subscription: DueSubscription) -> tuple[str, int | None]:
        claim_lease_expires_at = (
            temporalio.workflow.now() + SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT + SUBSCRIPTION_CLAIM_LEASE_SAFETY_MARGIN
        ).isoformat()
        child = _build_scheduled_subscription_child(
            subscription,
            scheduler_claim_lease_expires_at=claim_lease_expires_at,
        )
        claim_inputs = (
            SubscriptionSchedulerClaimInputs(
                claim_id=subscription.scheduler_claim_id,
                claim_token=subscription.scheduler_claim_token,
                lease_expires_at=claim_lease_expires_at,
            )
            if subscription.scheduler_claim_id and subscription.scheduler_claim_token
            else None
        )
        if claim_inputs is None:
            return "failed", subscription.subscription_id
        try:
            await temporalio.workflow.start_child_workflow(
                child.workflow,
                child.inputs,
                id=child.workflow_id,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=SUBSCRIPTION_WORKFLOW_EXECUTION_TIMEOUT,
            )
            return "accepted", None
        except WorkflowAlreadyStartedError:
            temporalio.workflow.logger.info(
                "process_subscription.already_running",
                extra={"subscription_id": subscription.subscription_id},
            )
            try:
                await temporalio.workflow.execute_activity(
                    release_subscription_scheduler_claim_activity,
                    claim_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                temporalio.workflow.logger.exception(
                    "subscription_scheduler.claim_release_failed",
                    extra={"subscription_id": subscription.subscription_id},
                )
            return "already_running", None
        except Exception as error:
            temporalio.workflow.logger.warning(
                "process_subscription.child_workflow_start_error",
                extra={"subscription_id": subscription.subscription_id, "error": str(error)},
            )
            try:
                await temporalio.workflow.execute_activity(
                    release_subscription_scheduler_claim_activity,
                    claim_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                temporalio.workflow.logger.exception(
                    "subscription_scheduler.claim_release_failed",
                    extra={"subscription_id": subscription.subscription_id},
                )
            return "failed", subscription.subscription_id

    results = await asyncio.gather(*(start_one(subscription) for subscription in unique_subscription_infos))
    accepted = sum(outcome == "accepted" for outcome, _ in results)
    already_running = sum(outcome == "already_running" for outcome, _ in results)
    failed_ids = [subscription_id for outcome, subscription_id in results if outcome == "failed" and subscription_id]

    _record_subscription_dispatch_outcome(region, "accepted", accepted)
    _record_subscription_dispatch_outcome(region, "already_running", already_running)
    _record_subscription_dispatch_outcome(region, "failed", len(failed_ids))
    temporalio.workflow.logger.info(
        "subscription_scheduler.dispatch_completed",
        extra={
            "accepted_count": accepted,
            "already_running_count": already_running,
            "failed_count": len(failed_ids),
        },
    )
    if failed_ids:
        raise ApplicationError(
            f"Failed to start {len(failed_ids)} subscription deliveries; first IDs: {failed_ids[:50]}",
            non_retryable=True,
        )


def _scheduler_claim_inputs(inputs: TrackedSubscriptionInputs) -> SubscriptionSchedulerClaimInputs | None:
    if inputs.scheduler_claim_id is None and inputs.scheduler_claim_token is None:
        return None
    if not inputs.scheduler_claim_id or not inputs.scheduler_claim_token:
        raise ApplicationError("Scheduled subscription claim input is incomplete", non_retryable=True)
    return SubscriptionSchedulerClaimInputs(
        claim_id=inputs.scheduler_claim_id,
        claim_token=inputs.scheduler_claim_token,
        lease_expires_at=inputs.scheduler_claim_lease_expires_at,
    )


async def _advance_subscription_schedule(inputs: TrackedSubscriptionInputs) -> bool | None:
    if inputs.scheduled_at and temporalio.workflow.patched("subscription-idempotent-schedule-advance-v1"):
        return await temporalio.workflow.execute_activity(
            advance_next_delivery_date_v2,
            AdvanceNextDeliveryDateInputs(
                subscription_id=inputs.subscription_id,
                expected_next_delivery_date=inputs.scheduled_at,
            ),
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
        )
    return await temporalio.workflow.execute_activity(
        advance_next_delivery_date,
        inputs.subscription_id,
        start_to_close_timeout=dt.timedelta(minutes=2),
        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
    )


async def _confirm_subscription_scheduler_claim(inputs: SubscriptionSchedulerClaimInputs | None) -> None:
    if inputs is None:
        return
    confirmed = await temporalio.workflow.execute_activity(
        confirm_subscription_scheduler_claim_activity,
        inputs,
        start_to_close_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
    )
    if not confirmed:
        raise ApplicationError("Scheduled subscription claim is no longer owned by this workflow", non_retryable=True)


async def _finish_subscription_scheduler_claim(
    inputs: SubscriptionSchedulerClaimInputs | None,
    *,
    schedule_advanced: bool,
) -> bool:
    if inputs is None:
        return True
    activity = (
        complete_subscription_scheduler_claim_activity
        if schedule_advanced
        else release_subscription_scheduler_claim_activity
    )
    return await temporalio.workflow.execute_activity(
        activity,
        inputs,
        start_to_close_timeout=dt.timedelta(minutes=1),
        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
    )


@temporalio.workflow.defn(name="schedule-all-subscriptions")
class ScheduleAllSubscriptionsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ScheduleAllSubscriptionsWorkflowInputs:
        if not inputs:
            return ScheduleAllSubscriptionsWorkflowInputs()

        loaded = json.loads(inputs[0])
        return ScheduleAllSubscriptionsWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ScheduleAllSubscriptionsWorkflowInputs) -> None:
        durable_dispatch = temporalio.workflow.patched("subscription-scheduler-durable-dispatch-v1")
        if durable_dispatch:
            try:
                await temporalio.workflow.execute_activity(
                    recover_subscription_scheduler_claims_activity,
                    RecoverSubscriptionSchedulerClaimsInputs(
                        region=inputs.region,
                        limit=inputs.max_subscriptions_per_run,
                    ),
                    start_to_close_timeout=SUBSCRIPTION_RECOVERY_ACTIVITY_TIMEOUT,
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                temporalio.workflow.logger.exception("subscription_scheduler.claim_recovery_failed")

        fetch_inputs = FetchDueSubscriptionsActivityInputs(
            buffer_minutes=inputs.buffer_minutes,
            max_subscriptions_per_run=inputs.max_subscriptions_per_run,
            region=inputs.region,
            use_durable_claims=durable_dispatch,
            claim_token_seed=temporalio.workflow.info().run_id if durable_dispatch else None,
        )
        if durable_dispatch:
            page = await temporalio.workflow.execute_activity(
                fetch_claimed_due_subscriptions_activity,
                fetch_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                    non_retryable_error_types=[],
                ),
            )
            region = page.region or inputs.region or "local"
            await _start_claimed_subscription_children(page.subscriptions, region)
            if page.next_discovery_cursor is not None:
                advanced = await temporalio.workflow.execute_activity(
                    advance_subscription_scheduler_cursor_activity,
                    AdvanceSubscriptionSchedulerCursorInputs(
                        region=region,
                        expected_discovery_cursor=page.expected_discovery_cursor,
                        next_discovery_cursor=page.next_discovery_cursor,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=temporalio.common.RetryPolicy(maximum_attempts=3),
                )
                if not advanced:
                    raise ApplicationError("Subscription scheduler cursor changed concurrently", non_retryable=True)
        else:
            subscription_infos: list[DueSubscription] = await temporalio.workflow.execute_activity(
                fetch_due_subscriptions_activity,
                fetch_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                    non_retryable_error_types=[],
                ),
            )
            await _run_legacy_subscription_children(subscription_infos)


@temporalio.workflow.defn(name="process-subscription")
class ProcessSubscriptionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrackedSubscriptionInputs:
        loaded = json.loads(inputs[0])
        if "previous_target_value" not in loaded and "previous_value" in loaded:
            loaded["previous_target_value"] = loaded["previous_value"]
        return TrackedSubscriptionInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TrackedSubscriptionInputs) -> None:
        scheduler_claim = (
            _scheduler_claim_inputs(inputs)
            if temporalio.workflow.patched("subscription-scheduler-claimed-child-v1")
            else None
        )
        await _confirm_subscription_scheduler_claim(scheduler_claim)
        schedule_advanced = inputs.trigger_type != SubscriptionTriggerType.SCHEDULED
        assets_with_content = 0
        total_assets = 0
        asset_errors: list[ExportError] = []
        asset_failure_summary: dict[str, str | int | list[str]] | None = None
        caught_error: BaseException | None = None
        delivery_error: NoExportableInsightsErrorDetails | None = None
        failure_stage = SubscriptionFailureStage.DELIVERY_RECORD

        # Delivery record tracking
        delivery_id: uuid.UUID | None = None
        final_status = DeliveryStatus.SKIPPED
        delivery_exported_asset_ids: list[int] = []
        delivery_recipient_results: list[dict] = []
        # Hoisted so the finally block can always pass it to update_delivery_record,
        # even on early returns (no-assets SKIPPED) or exceptions before the summary
        # activity runs.
        change_summary: str | None = None
        summary_skipped_over_budget = False

        try:
            # Create delivery history record — uuid4() is deterministic across
            # activity retries (replay) but unique across workflow retries.
            delivery_id = await temporalio.workflow.execute_activity(
                create_delivery_record,
                CreateDeliveryRecordInputs(
                    subscription_id=inputs.subscription_id,
                    team_id=inputs.team_id,
                    trigger_type=inputs.trigger_type,
                    scheduled_at=inputs.scheduled_at,
                    temporal_workflow_id=temporalio.workflow.info().workflow_id,
                    idempotency_key=str(temporalio.workflow.uuid4()),
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
            )

            # Validate up-front: if the subscription is already disabled or its target
            # configuration is permanently broken, auto-disable and short-circuit before
            # the export pipeline runs.
            failure_stage = SubscriptionFailureStage.VALIDATION
            abort_info = await temporalio.workflow.execute_activity(
                validate_subscription_for_delivery,
                inputs.subscription_id,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=SUBSCRIPTION_VALIDATE_RETRY_POLICY,
            )
            if abort_info is not None:
                # Just-disabled → FAILED with reason. Already-disabled (no failed_recipient) → SKIPPED default.
                if abort_info.failed_recipient is not None:
                    delivery_recipient_results = _to_recipient_dicts([abort_info.failed_recipient])
                    final_status = DeliveryStatus.FAILED
                return

            # Phase 1: Prepare — create ExportedAssets and persist insight snapshots
            # onto SubscriptionDelivery.content_snapshot (written from within the
            # activity to avoid shipping multi-MB query_results across Temporal's
            # ~2 MiB payload boundary).
            failure_stage = SubscriptionFailureStage.ASSET_PREPARATION
            prepare_result = await temporalio.workflow.execute_activity(
                create_export_assets,
                CreateExportAssetsInputs(
                    subscription_id=inputs.subscription_id,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )
            if inputs.slo:
                inputs.slo.completion_properties.update(
                    {
                        "target_type": prepare_result.target_type,
                        "selected_insight_count": prepare_result.selected_insight_count,
                        "available_insight_count": prepare_result.available_insight_count,
                    }
                )

            if not prepare_result.exported_asset_ids:
                if prepare_result.status == ExportAssetPreparationStatus.NO_EXPORTABLE_INSIGHTS:
                    failure_context = prepare_result.failure_context
                    if failure_context is None:
                        raise ApplicationError(
                            "No-exportable-insights result missing failure context", non_retryable=True
                        )
                    delivery_error = NoExportableInsightsErrorDetails(
                        message="This subscription has no available insights to export. Add insights to the dashboard or update the subscription's insight selection.",
                        type=ExportAssetPreparationStatus.NO_EXPORTABLE_INSIGHTS,
                        reason=failure_context["reason"],
                        resource_type=failure_context["resource_type"],
                        available_insight_count=failure_context["available_insight_count"],
                        selected_insight_count=failure_context["selected_insight_count"],
                    )
                    final_status = DeliveryStatus.FAILED
                    temporalio.workflow.logger.warning(
                        "process_subscription.no_exportable_insights",
                        extra={
                            "subscription_id": inputs.subscription_id,
                            "trigger_type": inputs.trigger_type,
                            "error_type": ExportAssetPreparationStatus.NO_EXPORTABLE_INSIGHTS,
                            **failure_context,
                        },
                    )
                    if inputs.slo:
                        inputs.slo.completion_properties.update(
                            {
                                "error_type": ExportAssetPreparationStatus.NO_EXPORTABLE_INSIGHTS,
                                "error_message": delivery_error["message"],
                                "failure_type": "configuration",
                                **failure_context,
                            }
                        )
                return

            delivery_exported_asset_ids = prepare_result.exported_asset_ids

            # Phase 2: Fan-out export — one activity per insight, independent retry
            failure_stage = SubscriptionFailureStage.ASSET_GENERATION
            export_tasks = []
            for asset_id in prepare_result.exported_asset_ids:
                task = temporalio.workflow.execute_activity(
                    export_asset_activity,
                    ExportAssetActivityInputs(
                        exported_asset_id=asset_id,
                        source=EventSource.SUBSCRIPTION,
                    ),
                    start_to_close_timeout=dt.timedelta(hours=1),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=EXPORT_RETRY_POLICY,
                )
                export_tasks.append((asset_id, task))

            # Gather results — continue on failure (partial success OK)
            export_results: list[ExportAssetResult | BaseException] = await asyncio.gather(
                *[task for _, task in export_tasks],
                return_exceptions=True,
            )

            # Classify export results
            asset_ids = [aid for aid, _ in export_tasks]
            outcome_assets, successful_asset_ids = _build_outcome_assets(asset_ids, export_results)
            assets_with_content = len(successful_asset_ids)
            total_assets = len(outcome_assets)
            asset_errors = [a.error for a in outcome_assets if a.error]

            non_user_errors = [e for e in asset_errors if not is_user_query_export_error(e)]
            if inputs.slo and non_user_errors:
                inputs.slo.outcome = SloOutcome.FAILURE
                distinct_classes = sorted({e.exception_class for e in non_user_errors})
                inputs.slo.completion_properties.setdefault("error_type", "PartialExportFailure")
                inputs.slo.completion_properties.setdefault(
                    "error_message",
                    f"{len(non_user_errors)} export(s) failed: {', '.join(distinct_classes)}",
                )
                asset_failure_summary = _summarize_export_failure_details(non_user_errors)

            # Generate LLM change summary (best-effort, skip if not enabled).
            # Reads content_snapshot back from Postgres — persisted inline by
            # create_export_assets above via delivery_id.
            if delivery_id is not None:
                try:
                    snapshot_result = await temporalio.workflow.execute_activity(
                        snapshot_subscription_insights,
                        SnapshotInsightsInputs(
                            subscription_id=inputs.subscription_id,
                            team_id=inputs.team_id,
                            delivery_id=str(delivery_id),
                            exported_asset_ids=list(successful_asset_ids),
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        heartbeat_timeout=dt.timedelta(seconds=60),
                        retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                    )
                    change_summary = snapshot_result.summary_text
                    summary_skipped_over_budget = snapshot_result.summary_skipped_over_budget
                except Exception:
                    temporalio.workflow.logger.warning(
                        "process_subscription.snapshot_failed",
                        extra={"subscription_id": inputs.subscription_id},
                    )

            # Phase 3: Deliver — send all assets including failed ones (they show
            # a "failed to generate" placeholder in the email/Slack message)
            delivery_asset_ids = prepare_result.exported_asset_ids

            delivery_activity = (
                deliver_subscription_v2
                if temporalio.workflow.patched("subscription-delivery-campaign-v2")
                else deliver_subscription
            )
            failure_stage = SubscriptionFailureStage.DELIVERY
            deliver_result: DeliverSubscriptionResult = await temporalio.workflow.execute_activity(
                delivery_activity,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=delivery_asset_ids,
                    total_insight_count=prepare_result.total_insight_count,
                    previous_target_value=inputs.previous_target_value,
                    previous_value=(
                        inputs.previous_target_value
                        if inputs.previous_target_value is not None
                        else inputs.previous_value
                    ),
                    invite_message=inputs.invite_message,
                    change_summary=change_summary,
                    summary_skipped_over_budget=summary_skipped_over_budget,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT,
                retry_policy=SUBSCRIPTION_DELIVER_RETRY_POLICY,
            )

            # Capture per-recipient results for the delivery record
            delivery_recipient_results = _to_recipient_dicts(deliver_result.recipient_results)
            final_status = (
                DeliveryStatus.FAILED
                if delivery_recipient_results
                and all(result["status"] == "failed" for result in delivery_recipient_results)
                else DeliveryStatus.COMPLETED
            )

        except Exception as e:
            # Preserve recipient outcomes carried in non-retryable delivery errors
            # (e.g. Slack missing integration) so history isn't empty on failure.
            if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError):
                details = e.cause.details
                if details and isinstance(details[0], dict):
                    recipient_results = details[0].get("recipient_results")
                    if isinstance(recipient_results, list):
                        delivery_recipient_results = recipient_results
            _record_subscription_failure(inputs.slo, failure_stage, e)
            caught_error = e
            final_status = DeliveryStatus.FAILED
            # Defer the re-raise until after the finally block — see note below.

        finally:
            delivery_failed_before_record_update = caught_error is not None
            # Finalize delivery record with whatever state we have
            if delivery_id is not None:
                try:
                    await temporalio.workflow.execute_activity(
                        update_delivery_record,
                        UpdateDeliveryRecordInputs(
                            delivery_id=delivery_id,
                            status=final_status,
                            exported_asset_ids=delivery_exported_asset_ids or None,
                            recipient_results=delivery_recipient_results or None,
                            change_summary=change_summary,
                            error=(
                                {"message": str(caught_error)[:500], "type": type(caught_error).__name__}
                                if caught_error
                                else delivery_error
                            ),
                            finished=True,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                    )
                except Exception as update_error:
                    temporalio.workflow.logger.exception(
                        "update_delivery_record failed (delivery history is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        _record_subscription_failure(inputs.slo, SubscriptionFailureStage.RECORD_UPDATE, update_error)
                        if scheduler_claim is None:
                            raise
                        caught_error = update_error

            delivery_failed_without_exception = bool(delivery_recipient_results) and all(
                result["status"] == "failed" for result in delivery_recipient_results
            )
            if (
                delivery_id is not None
                and temporalio.workflow.patched("subscription-delivery-failure-notification-2026-08")
                and (delivery_failed_before_record_update or delivery_failed_without_exception)
                and inputs.trigger_type == SubscriptionTriggerType.SCHEDULED
            ):
                try:
                    await temporalio.workflow.execute_activity(
                        notify_subscription_delivery_failure,
                        args=[inputs.subscription_id, str(delivery_id)],
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "process_subscription.failure_notification_failed",
                        extra={"subscription_id": inputs.subscription_id},
                    )

            # Advance schedule — always for scheduled deliveries, even on failure.
            # The activity itself no-ops when the subscription is disabled, so a
            # just-auto-disabled sub doesn't get a misleading future delivery date.
            if inputs.trigger_type == SubscriptionTriggerType.SCHEDULED:
                try:
                    advance_result = await _advance_subscription_schedule(inputs)
                    schedule_advanced = (
                        advance_result is not False
                        if temporalio.workflow.patched("subscription-scheduler-advance-result-v1")
                        else True
                    )
                except Exception as schedule_error:
                    temporalio.workflow.logger.exception(
                        "advance_next_delivery_date failed (schedule update is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        _record_subscription_failure(
                            inputs.slo, SubscriptionFailureStage.SCHEDULE_UPDATE, schedule_error
                        )
                        if scheduler_claim is None:
                            raise
                        caught_error = schedule_error

            try:
                claim_finished = await _finish_subscription_scheduler_claim(
                    scheduler_claim,
                    schedule_advanced=schedule_advanced,
                )
            except Exception as claim_error:
                temporalio.workflow.logger.exception("subscription_scheduler.claim_finalization_failed")
                if caught_error is None:
                    caught_error = claim_error
            else:
                if not claim_finished and caught_error is None:
                    caught_error = ApplicationError(
                        "Scheduled subscription claim could not reach a terminal state",
                        non_retryable=True,
                    )

            # Enrich SLO event with per-insight detail (non-user errors only).
            if inputs.slo:
                if caught_error is None and asset_failure_summary is not None:
                    inputs.slo.completion_properties.update(asset_failure_summary)
                inputs.slo.completion_properties.update(
                    {
                        "assets_with_content": assets_with_content,
                        "total_assets": total_assets,
                        "asset_errors": [
                            {
                                "error_type": e.exception_class,
                                "error_trace": e.error_trace,
                                **(e.failure_details or {}),
                            }
                            for e in asset_errors
                            if not is_user_query_export_error(e)
                        ],
                    }
                )

            # A return from the delivery body resumes after finally. Raise here,
            # after all cleanup commands, so a lost claim transition cannot turn
            # an early abort into a successful workflow.
            if scheduler_claim is not None and caught_error:
                raise caught_error

        # Re-raise after cleanup completes. We can't re-raise inside the except
        # block because Temporal's SDK blocks new activity scheduling in the
        # finally block while an exception is propagating.
        if caught_error:
            raise caught_error


@temporalio.workflow.defn(name="process-ai-subscription")
class ProcessAISubscriptionWorkflow(PostHogWorkflow):
    """Scheduled delivery for AI-prompt subs: create-record -> validate -> generate (LLM) -> deliver.

    The lifecycle scaffolding mirrors ProcessSubscriptionWorkflow (only the middle phase
    differs); keep the two in sync. Not a shared base — Temporal workflow classes can't
    share run-method control flow without sandbox-determinism risk.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrackedSubscriptionInputs:
        loaded = json.loads(inputs[0])
        return TrackedSubscriptionInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TrackedSubscriptionInputs) -> None:
        scheduler_claim = (
            _scheduler_claim_inputs(inputs)
            if temporalio.workflow.patched("subscription-scheduler-claimed-child-v1")
            else None
        )
        await _confirm_subscription_scheduler_claim(scheduler_claim)
        schedule_advanced = inputs.trigger_type != SubscriptionTriggerType.SCHEDULED
        delivery_id: uuid.UUID | None = None
        final_status = DeliveryStatus.SKIPPED
        delivery_recipient_results: list[dict] = []
        caught_error: BaseException | None = None
        failure_stage = SubscriptionFailureStage.DELIVERY_RECORD
        # Set when a delivered-but-degraded report should record a reason without an exception
        # (every generated query failed). Falls through to update_delivery_record's error column.
        generation_error: dict | None = None

        try:
            delivery_id = await temporalio.workflow.execute_activity(
                create_delivery_record,
                CreateDeliveryRecordInputs(
                    subscription_id=inputs.subscription_id,
                    team_id=inputs.team_id,
                    trigger_type=inputs.trigger_type,
                    scheduled_at=inputs.scheduled_at,
                    temporal_workflow_id=temporalio.workflow.info().workflow_id,
                    idempotency_key=str(temporalio.workflow.uuid4()),
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
            )

            # Up-front validation: already-disabled (idempotency redispatch) or a
            # permanently broken target (e.g. unsupported target_type) auto-disables and
            # short-circuits before any LLM cost.
            failure_stage = SubscriptionFailureStage.VALIDATION
            abort_info = await temporalio.workflow.execute_activity(
                validate_subscription_for_delivery,
                inputs.subscription_id,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=SUBSCRIPTION_VALIDATE_RETRY_POLICY,
            )
            if abort_info is not None:
                # Just-disabled → FAILED with reason. Already-disabled (no failed_recipient)
                # → SKIPPED default (idempotency redispatch). Matches ProcessSubscriptionWorkflow.
                if abort_info.failed_recipient is not None:
                    delivery_recipient_results = _to_recipient_dicts([abort_info.failed_recipient])
                    final_status = DeliveryStatus.FAILED
                return

            # Phase 1: generate the report. Consent is gated inside, before any LLM cost.
            # The markdown is persisted onto the delivery row (read back by delivery),
            # never returned on the wire — it can exceed Temporal's ~2 MiB payload cap.
            failure_stage = SubscriptionFailureStage.REPORT_GENERATION
            generate_result = await temporalio.workflow.execute_activity(
                generate_ai_subscription_report,
                GenerateAIReportInputs(subscription_id=inputs.subscription_id, delivery_id=delivery_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=30),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=3,
                ),
            )
            if inputs.slo:
                inputs.slo.completion_properties["target_type"] = generate_result.target_type
            if generate_result.aborted:
                # Consent revoked or prompt invalid — generation already auto-disabled.
                delivery_recipient_results = _to_recipient_dicts(generate_result.recipient_results)
                final_status = DeliveryStatus.FAILED
                return

            if generate_result.skipped:
                # Over AI-credit budget — generation rescheduled the sub past the credit reset and
                # notified the owner. SKIPPED (not FAILED): the sub isn't broken, it resumes when
                # credits reset; advance_next_delivery_date (finally) recomputes from the reschedule.
                final_status = DeliveryStatus.SKIPPED
                return

            # Phase 2: ship the persisted report.
            delivery_activity = (
                deliver_subscription_v2
                if temporalio.workflow.patched("subscription-delivery-campaign-v2")
                else deliver_subscription
            )
            failure_stage = SubscriptionFailureStage.DELIVERY
            deliver_result = await temporalio.workflow.execute_activity(
                delivery_activity,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=[],
                    total_insight_count=0,
                    previous_target_value=inputs.previous_target_value,
                    previous_value=(
                        inputs.previous_target_value
                        if inputs.previous_target_value is not None
                        else inputs.previous_value
                    ),
                    invite_message=inputs.invite_message,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=SUBSCRIPTION_DELIVER_ATTEMPT_TIMEOUT,
                retry_policy=SUBSCRIPTION_DELIVER_RETRY_POLICY,
            )
            delivery_recipient_results = _to_recipient_dicts(deliver_result.recipient_results)

            # A report whose every generated query failed computed no metrics, so it records FAILED with
            # the failure detail the delivery history surfaces on hover (see delivered_status). The report
            # email already went out above (with the leading failure notice), so FAILED here means "empty
            # report", not "not delivered" — recipient_results can still show successful sends. Partial
            # failures stay COMPLETED; their per-query diagnostics live in content_snapshot for the viewer.
            final_status, generation_error = generate_result.delivered_status()

        except Exception as e:
            # Preserve recipient outcomes carried in non-retryable delivery errors so the
            # delivery history isn't empty on failure (matches ProcessSubscriptionWorkflow).
            if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError):
                details = e.cause.details
                if details and isinstance(details[0], dict):
                    recipient_results = details[0].get("recipient_results")
                    if isinstance(recipient_results, list):
                        delivery_recipient_results = recipient_results
            _record_subscription_failure(inputs.slo, failure_stage, e)
            caught_error = e
            final_status = DeliveryStatus.FAILED

        finally:
            delivery_failed_before_record_update = caught_error is not None
            if delivery_id is not None:
                try:
                    await temporalio.workflow.execute_activity(
                        update_delivery_record,
                        UpdateDeliveryRecordInputs(
                            delivery_id=delivery_id,
                            status=final_status,
                            recipient_results=delivery_recipient_results or None,
                            error={"message": str(caught_error)[:500], "type": type(caught_error).__name__}
                            if caught_error
                            else generation_error,
                            finished=True,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                    )
                except Exception as update_error:
                    temporalio.workflow.logger.exception(
                        "update_delivery_record failed (delivery history is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        _record_subscription_failure(inputs.slo, SubscriptionFailureStage.RECORD_UPDATE, update_error)
                        if scheduler_claim is None:
                            raise
                        caught_error = update_error

            if (
                delivery_id is not None
                and temporalio.workflow.patched("subscription-delivery-failure-notification-2026-08")
                and delivery_failed_before_record_update
                and inputs.trigger_type == SubscriptionTriggerType.SCHEDULED
            ):
                try:
                    await temporalio.workflow.execute_activity(
                        notify_subscription_delivery_failure,
                        args=[inputs.subscription_id, str(delivery_id)],
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "process_ai_subscription.failure_notification_failed",
                        extra={"subscription_id": inputs.subscription_id},
                    )

            # Advance schedule for scheduled deliveries even on failure — the activity
            # no-ops when the subscription is disabled, so a just-auto-disabled sub
            # doesn't get a misleading future delivery date.
            if inputs.trigger_type == SubscriptionTriggerType.SCHEDULED:
                try:
                    advance_result = await _advance_subscription_schedule(inputs)
                    schedule_advanced = (
                        advance_result is not False
                        if temporalio.workflow.patched("subscription-scheduler-advance-result-v1")
                        else True
                    )
                except Exception as schedule_error:
                    temporalio.workflow.logger.exception(
                        "advance_next_delivery_date failed (schedule update is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        _record_subscription_failure(
                            inputs.slo, SubscriptionFailureStage.SCHEDULE_UPDATE, schedule_error
                        )
                        if scheduler_claim is None:
                            raise
                        caught_error = schedule_error

            try:
                claim_finished = await _finish_subscription_scheduler_claim(
                    scheduler_claim,
                    schedule_advanced=schedule_advanced,
                )
            except Exception as claim_error:
                temporalio.workflow.logger.exception("subscription_scheduler.claim_finalization_failed")
                if caught_error is None:
                    caught_error = claim_error
            else:
                if not claim_finished and caught_error is None:
                    caught_error = ApplicationError(
                        "Scheduled subscription claim could not reach a terminal state",
                        non_retryable=True,
                    )

            # Auto-disable aborts (consent revoked / prompt invalid) return normally rather
            # than raising, so they record delivery status FAILED but keep the SLO outcome
            # SUCCESS — a user-config terminal state is not a platform failure (matches the
            # non-AI auto-disable convention). Genuine errors set caught_error and re-raise
            # below; SloInterceptor maps the exception to a FAILURE outcome, same as
            # ProcessSubscriptionWorkflow, so we don't set the outcome here.
            if inputs.slo:
                inputs.slo.completion_properties.setdefault("resource_type", AI_PROMPT_RESOURCE_TYPE)

            if scheduler_claim is not None and caught_error:
                raise caught_error

        # Re-raise after cleanup completes — Temporal blocks activity scheduling in the
        # finally block while an exception is propagating.
        if caught_error:
            raise caught_error


@temporalio.workflow.defn(name="handle-subscription-value-change")
class HandleSubscriptionValueChangeWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessSubscriptionWorkflowInputs:
        loaded = json.loads(inputs[0])
        if "previous_target_value" not in loaded and "previous_value" in loaded:
            loaded["previous_target_value"] = loaded["previous_value"]
        return ProcessSubscriptionWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ProcessSubscriptionWorkflowInputs) -> None:
        tracked = TrackedSubscriptionInputs(
            subscription_id=inputs.subscription_id,
            team_id=inputs.team_id,
            distinct_id=inputs.distinct_id,
            previous_target_value=inputs.previous_target_value,
            previous_value=(
                inputs.previous_target_value if inputs.previous_target_value is not None else inputs.previous_value
            ),
            invite_message=inputs.invite_message,
            trigger_type=inputs.trigger_type,
            resource_type=inputs.resource_type,
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=inputs.team_id,
                resource_id=str(inputs.subscription_id),
                distinct_id=inputs.distinct_id,
                start_properties={
                    "resource_type": inputs.resource_type,
                    "trigger_type": inputs.trigger_type,
                },
                completion_properties={
                    "resource_type": inputs.resource_type,
                    "trigger_type": inputs.trigger_type,
                },
            ),
        )
        # Route AI-prompt subs (test delivery / target change) to the AI workflow, same
        # as the scheduler fan-out.
        child_workflow: Callable[..., Coroutine[Any, Any, None]]
        if inputs.resource_type == AI_PROMPT_RESOURCE_TYPE:
            child_workflow = ProcessAISubscriptionWorkflow.run
            child_id = f"process-ai-subscription-{inputs.trigger_type}-{inputs.subscription_id}"
        else:
            child_workflow = ProcessSubscriptionWorkflow.run
            child_id = f"process-subscription-{inputs.trigger_type}-{inputs.subscription_id}"
        await temporalio.workflow.execute_child_workflow(
            child_workflow,
            tracked,
            id=child_id,
            parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
            execution_timeout=dt.timedelta(hours=2),
        )
