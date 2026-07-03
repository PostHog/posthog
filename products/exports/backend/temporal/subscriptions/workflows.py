import json
import uuid
import asyncio
import datetime as dt
import dataclasses
from collections.abc import Callable, Coroutine
from typing import Any

import temporalio.common
import temporalio.workflow
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

from posthog.event_usage import EventSource
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.retry_policy import EXPORT_RETRY_POLICY
from posthog.temporal.exports.types import (
    ExportAssetActivityInputs,
    ExportAssetResult,
    ExportError,
    extract_error_details,
)

from products.exports.backend.tasks.failure_handler import is_user_query_error_type
from products.exports.backend.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_delivery_record,
    create_export_assets,
    deliver_subscription,
    fetch_due_subscriptions_activity,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.retry_policy import (
    SUBSCRIPTION_DELIVER_RETRY_POLICY,
    SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
    SUBSCRIPTION_VALIDATE_RETRY_POLICY,
)
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import (
    AI_PROMPT_RESOURCE_TYPE,
    CreateDeliveryRecordInputs,
    CreateExportAssetsInputs,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    DeliveryStatus,
    FetchDueSubscriptionsActivityInputs,
    GenerateAIReportInputs,
    ProcessSubscriptionWorkflowInputs,
    RecipientResult,
    ScheduleAllSubscriptionsWorkflowInputs,
    SnapshotInsightsInputs,
    SubscriptionInfo,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
    UpdateDeliveryRecordInputs,
)


def _to_recipient_dicts(recipient_results: list[RecipientResult]) -> list[dict]:
    return [
        {"recipient": r.recipient, "status": r.status, **({"error": r.error} if r.error else {})}
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
        fetch_inputs = FetchDueSubscriptionsActivityInputs(buffer_minutes=inputs.buffer_minutes)
        subscription_infos: list[SubscriptionInfo] = await temporalio.workflow.execute_activity(
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

        # Fan-out child workflows — one per subscription, fully isolated.
        # Deterministic ID (no run_id suffix) prevents duplicate deliveries when
        # schedule runs overlap: Temporal guarantees no two open workflows can
        # share the same ID, so a still-running child rejects the duplicate start.
        tasks = []
        for sub in subscription_infos:
            tracked = TrackedSubscriptionInputs(
                subscription_id=sub.subscription_id,
                team_id=sub.team_id,
                distinct_id=sub.distinct_id,
                trigger_type=SubscriptionTriggerType.SCHEDULED,
                scheduled_at=sub.next_delivery_date,
                resource_type=sub.resource_type,
                slo=SloConfig(
                    operation=SloOperation.SUBSCRIPTION_DELIVERY,
                    area=SloArea.ANALYTIC_PLATFORM,
                    team_id=sub.team_id,
                    resource_id=str(sub.subscription_id),
                    distinct_id=sub.distinct_id,
                ),
            )
            # AI-prompt subs run a dedicated workflow; distinct child-ID prefixes keep the
            # overlapping-duplicate guarantee per type.
            workflow: Callable[..., Coroutine[Any, Any, None]]
            if sub.resource_type == AI_PROMPT_RESOURCE_TYPE:
                workflow = ProcessAISubscriptionWorkflow.run
                child_id = f"process-ai-subscription-{sub.subscription_id}"
            else:
                workflow = ProcessSubscriptionWorkflow.run
                child_id = f"process-subscription-{sub.subscription_id}"
            task = temporalio.workflow.execute_child_workflow(
                workflow,
                tracked,
                id=child_id,
                parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                execution_timeout=dt.timedelta(hours=2),
            )
            tasks.append(task)

        if tasks:
            # return_exceptions=True: individual subscription failures are isolated —
            # one failing subscription should not prevent others from being delivered.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            failed_ids = []
            for sub, result in zip(subscription_infos, results):
                if isinstance(result, BaseException):
                    if isinstance(result, WorkflowAlreadyStartedError):
                        # A previous schedule run's child is still processing this
                        # subscription — not a failure, just skip it.
                        temporalio.workflow.logger.info(
                            "process_subscription.already_running",
                            extra={"subscription_id": sub.subscription_id},
                        )
                    else:
                        failed_ids.append(sub.subscription_id)
                        temporalio.workflow.logger.warning(
                            "process_subscription.child_workflow_error",
                            extra={"subscription_id": sub.subscription_id, "error": str(result)},
                        )

            if failed_ids:
                raise ApplicationError(
                    f"Subscription deliveries failed for IDs: {failed_ids}",
                    non_retryable=True,
                )


@temporalio.workflow.defn(name="process-subscription")
class ProcessSubscriptionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> TrackedSubscriptionInputs:
        loaded = json.loads(inputs[0])
        return TrackedSubscriptionInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TrackedSubscriptionInputs) -> None:
        assets_with_content = 0
        total_assets = 0
        asset_errors: list[ExportError] = []
        caught_error: BaseException | None = None

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
            abort_info = await temporalio.workflow.execute_activity(
                validate_subscription_for_delivery,
                inputs.subscription_id,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=SUBSCRIPTION_VALIDATE_RETRY_POLICY,
            )
            if abort_info is not None:
                # Just-disabled → FAILED with reason. Already-disabled (no failed_recipient) → SKIPPED default.
                if abort_info.failed_recipient is not None:
                    delivery_recipient_results = [dataclasses.asdict(abort_info.failed_recipient)]
                    final_status = DeliveryStatus.FAILED
                return

            # Phase 1: Prepare — create ExportedAssets and persist insight snapshots
            # onto SubscriptionDelivery.content_snapshot (written from within the
            # activity to avoid shipping multi-MB query_results across Temporal's
            # ~2 MiB payload boundary).
            prepare_result = await temporalio.workflow.execute_activity(
                create_export_assets,
                CreateExportAssetsInputs(
                    subscription_id=inputs.subscription_id,
                    previous_value=inputs.previous_value,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=2),
                    maximum_attempts=3,
                ),
            )

            if not prepare_result.exported_asset_ids:
                # No assets to export — SKIPPED status, finalized in finally
                return

            delivery_exported_asset_ids = prepare_result.exported_asset_ids

            # Phase 2: Fan-out export — one activity per insight, independent retry
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

            non_user_errors = [e for e in asset_errors if not is_user_query_error_type(e.exception_class)]
            if inputs.slo and non_user_errors:
                inputs.slo.outcome = SloOutcome.FAILURE
                distinct_classes = sorted({e.exception_class for e in non_user_errors})
                inputs.slo.completion_properties.setdefault("error_type", "PartialExportFailure")
                inputs.slo.completion_properties.setdefault(
                    "error_message",
                    f"{len(non_user_errors)} export(s) failed: {', '.join(distinct_classes)}",
                )

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

            # is_new is true for target change triggers, false for scheduled and manual sends
            is_new = inputs.trigger_type == SubscriptionTriggerType.TARGET_CHANGE

            deliver_result: DeliverSubscriptionResult = await temporalio.workflow.execute_activity(
                deliver_subscription,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=delivery_asset_ids,
                    total_insight_count=prepare_result.total_insight_count,
                    is_new_subscription_target=is_new,
                    previous_value=inputs.previous_value,
                    invite_message=inputs.invite_message,
                    change_summary=change_summary,
                    summary_skipped_over_budget=summary_skipped_over_budget,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=SUBSCRIPTION_DELIVER_RETRY_POLICY,
            )

            # Capture per-recipient results for the delivery record
            delivery_recipient_results = _to_recipient_dicts(deliver_result.recipient_results)
            final_status = DeliveryStatus.COMPLETED

        except Exception as e:
            # Preserve recipient outcomes carried in non-retryable delivery errors
            # (e.g. Slack missing integration) so history isn't empty on failure.
            if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError):
                details = e.cause.details
                if details and isinstance(details[0], dict):
                    recipient_results = details[0].get("recipient_results")
                    if isinstance(recipient_results, list):
                        delivery_recipient_results = recipient_results
            caught_error = e
            final_status = DeliveryStatus.FAILED
            # Defer the re-raise until after the finally block — see note below.

        finally:
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
                            error={"message": str(caught_error)[:500], "type": type(caught_error).__name__}
                            if caught_error
                            else None,
                            finished=True,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                    )
                except Exception:
                    temporalio.workflow.logger.exception(
                        "update_delivery_record failed (delivery history is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        raise

            # Advance schedule — always for scheduled deliveries, even on failure.
            # The activity itself no-ops when the subscription is disabled, so a
            # just-auto-disabled sub doesn't get a misleading future delivery date.
            if inputs.trigger_type == SubscriptionTriggerType.SCHEDULED:
                await temporalio.workflow.execute_activity(
                    advance_next_delivery_date,
                    inputs.subscription_id,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                )

            # Enrich SLO event with per-insight detail (non-user errors only).
            if inputs.slo:
                inputs.slo.completion_properties.update(
                    {
                        "assets_with_content": assets_with_content,
                        "total_assets": total_assets,
                        "asset_errors": [
                            {"error_type": e.exception_class, "error_trace": e.error_trace}
                            for e in asset_errors
                            if not is_user_query_error_type(e.exception_class)
                        ],
                    }
                )

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
        delivery_id: uuid.UUID | None = None
        final_status = DeliveryStatus.SKIPPED
        delivery_recipient_results: list[dict] = []
        caught_error: BaseException | None = None
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
                    delivery_recipient_results = [dataclasses.asdict(abort_info.failed_recipient)]
                    final_status = DeliveryStatus.FAILED
                return

            # Phase 1: generate the report. Consent is gated inside, before any LLM cost.
            # The markdown is persisted onto the delivery row (read back by delivery),
            # never returned on the wire — it can exceed Temporal's ~2 MiB payload cap.
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

            # Phase 2: ship the persisted report. is_new only for target-change triggers.
            is_new = inputs.trigger_type == SubscriptionTriggerType.TARGET_CHANGE
            deliver_result = await temporalio.workflow.execute_activity(
                deliver_subscription,
                DeliverSubscriptionInputs(
                    subscription_id=inputs.subscription_id,
                    exported_asset_ids=[],
                    total_insight_count=0,
                    is_new_subscription_target=is_new,
                    previous_value=inputs.previous_value,
                    invite_message=inputs.invite_message,
                    delivery_id=delivery_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=SUBSCRIPTION_DELIVER_RETRY_POLICY,
            )
            delivery_recipient_results = _to_recipient_dicts(deliver_result.recipient_results)

            # A report whose every generated query failed computed no metrics — recording that as
            # "completed" misrepresents an empty report, so mark it FAILED with the failure detail
            # the delivery history surfaces on hover. The report email already went out above (with
            # the leading failure notice), so FAILED here means "empty report", not "not delivered" —
            # recipient_results can still show successful sends. Partial failures stay COMPLETED; their
            # per-query diagnostics (generated HogQL + error type) live in content_snapshot for
            # the delivery detail view.
            if generate_result.all_queries_failed:
                final_status = DeliveryStatus.FAILED
                generation_error = generate_result.failure_error()
            else:
                final_status = DeliveryStatus.COMPLETED

        except Exception as e:
            # Preserve recipient outcomes carried in non-retryable delivery errors so the
            # delivery history isn't empty on failure (matches ProcessSubscriptionWorkflow).
            if isinstance(e, ActivityError) and isinstance(e.cause, ApplicationError):
                details = e.cause.details
                if details and isinstance(details[0], dict):
                    recipient_results = details[0].get("recipient_results")
                    if isinstance(recipient_results, list):
                        delivery_recipient_results = recipient_results
            caught_error = e
            final_status = DeliveryStatus.FAILED

        finally:
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
                except Exception:
                    temporalio.workflow.logger.exception(
                        "update_delivery_record failed (delivery history is best-effort when a prior error exists)"
                    )
                    if caught_error is None:
                        raise

            # Advance schedule for scheduled deliveries even on failure — the activity
            # no-ops when the subscription is disabled, so a just-auto-disabled sub
            # doesn't get a misleading future delivery date.
            if inputs.trigger_type == SubscriptionTriggerType.SCHEDULED:
                await temporalio.workflow.execute_activity(
                    advance_next_delivery_date,
                    inputs.subscription_id,
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=SUBSCRIPTION_RECORD_LIFECYCLE_RETRY_POLICY,
                )

            # Auto-disable aborts (consent revoked / prompt invalid) return normally rather
            # than raising, so they record delivery status FAILED but keep the SLO outcome
            # SUCCESS — a user-config terminal state is not a platform failure (matches the
            # non-AI auto-disable convention). Genuine errors set caught_error and re-raise
            # below; SloInterceptor maps the exception to a FAILURE outcome, same as
            # ProcessSubscriptionWorkflow, so we don't set the outcome here.
            if inputs.slo:
                inputs.slo.completion_properties.setdefault("resource_type", AI_PROMPT_RESOURCE_TYPE)

        # Re-raise after cleanup completes — Temporal blocks activity scheduling in the
        # finally block while an exception is propagating.
        if caught_error:
            raise caught_error


@temporalio.workflow.defn(name="handle-subscription-value-change")
class HandleSubscriptionValueChangeWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ProcessSubscriptionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ProcessSubscriptionWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ProcessSubscriptionWorkflowInputs) -> None:
        tracked = TrackedSubscriptionInputs(
            subscription_id=inputs.subscription_id,
            team_id=inputs.team_id,
            distinct_id=inputs.distinct_id,
            previous_value=inputs.previous_value,
            invite_message=inputs.invite_message,
            trigger_type=inputs.trigger_type,
            resource_type=inputs.resource_type,
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=inputs.team_id,
                resource_id=str(inputs.subscription_id),
                distinct_id=inputs.distinct_id,
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
