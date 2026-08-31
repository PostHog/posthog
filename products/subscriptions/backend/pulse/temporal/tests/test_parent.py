from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.conf import settings

from products.exports.backend.temporal.subscriptions import workflows as subscription_workflows
from products.exports.backend.temporal.subscriptions.types import (
    AI_PROMPT_RESOURCE_TYPE,
    DeliverSubscriptionResult,
    DueSubscription,
    GenerateAIReportResult,
    ScheduleAllSubscriptionsWorkflowInputs,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
)
from products.subscriptions.backend.pulse.temporal.inputs import (
    ProactiveDispatchSnapshot,
    PulseDeliveryBundleRef,
    PulseWorkflowInput,
    PulseWorkflowResult,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("patch_active", "expects_manifest"), [(True, True), (False, False)])
async def test_scheduler_prepares_one_manifest_before_fanning_out_ai_children(
    monkeypatch, patch_active: bool, expects_manifest: bool
) -> None:
    activity_calls: list[object] = []
    child_inputs: list[object] = []

    async def execute_activity(activity, *args, **_kwargs):
        activity_calls.append(activity)
        if activity is subscription_workflows.fetch_due_subscriptions_activity:
            return [
                DueSubscription(
                    subscription_id=2,
                    team_id=1,
                    distinct_id="distinct",
                    resource_type=AI_PROMPT_RESOURCE_TYPE,
                ),
                DueSubscription(subscription_id=3, team_id=1, distinct_id="distinct", resource_type="dashboard"),
            ]
        if activity is subscription_workflows.build_scheduled_proactive_snapshot_manifest:
            assert args[0].subscription_ids == [2]
            return "subscriptions/pulse/dispatch-manifests/v1/test.json"
        raise AssertionError(f"Unexpected activity: {activity}")

    async def execute_child_workflow(_workflow, child_input, **_kwargs):
        child_inputs.append(child_input)
        return None

    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_child_workflow", execute_child_workflow)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "patched", lambda _marker: patch_active)

    await subscription_workflows.ScheduleAllSubscriptionsWorkflow().run(ScheduleAllSubscriptionsWorkflowInputs())

    expected_activity_calls: list[object] = [subscription_workflows.fetch_due_subscriptions_activity]
    if expects_manifest:
        expected_activity_calls.append(subscription_workflows.build_scheduled_proactive_snapshot_manifest)
    assert activity_calls == expected_activity_calls
    ai_input = child_inputs[0]
    if expects_manifest:
        assert isinstance(ai_input, TrackedSubscriptionInputs)
        assert ai_input.proactive_snapshot_manifest_ref == "subscriptions/pulse/dispatch-manifests/v1/test.json"
    else:
        assert isinstance(ai_input, dict)
        assert "proactive_snapshot_manifest_ref" not in ai_input
    assert isinstance(child_inputs[1], dict)
    assert "proactive_snapshot_manifest_ref" not in child_inputs[1]


@pytest.mark.asyncio
async def test_parent_waits_for_enabled_pulse_child_before_delivery(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(
        version=1,
        enabled=True,
        config_snapshot_ref="pulse-config:1",
        wall_clock_budget_seconds=600,
        finalization_margin_seconds=60,
    )
    delivery_id = uuid4()
    pulse_input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=uuid4(),
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        deadline=datetime(2026, 8, 29, 12, 10, tzinfo=UTC),
        proactive_snapshot=snapshot,
    )
    expected = PulseWorkflowResult(
        pulse_run_id=pulse_input.pulse_run_id,
        status="completed",
        result_ref="pulse-result:1",
    )
    execute_activity = AsyncMock(return_value=pulse_input)
    execute_child = AsyncMock(return_value=expected)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_child_workflow", execute_child)
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC)
    )

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        ),
        delivery_id,
    )

    assert result == expected
    assert execute_activity.await_args is not None
    assert execute_activity.await_args.kwargs["task_queue"] == settings.PULSE_TASK_QUEUE
    execute_child.assert_awaited_once_with(
        subscription_workflows.PULSE_WORKFLOW_RUN,
        pulse_input,
        id=f"pulse:2:{delivery_id}",
        parent_close_policy=subscription_workflows.temporalio.workflow.ParentClosePolicy.REQUEST_CANCEL,
        execution_timeout=timedelta(minutes=10),
        id_reuse_policy=subscription_workflows.temporalio.common.WorkflowIDReusePolicy.REJECT_DUPLICATE,
        task_queue=settings.PULSE_TASK_QUEUE,
    )


@pytest.mark.asyncio
async def test_parent_records_child_failure_and_keeps_the_base_delivery_path(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    start_input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=uuid4(),
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        deadline=datetime(2026, 8, 29, 12, 10, tzinfo=UTC),
        proactive_snapshot=snapshot,
    )
    terminal = PulseWorkflowResult(
        pulse_run_id=start_input.pulse_run_id,
        status="failed",
        result_ref="pulse-result:failed",
        failure_code="pulse_child_failed",
    )
    execute_activity = AsyncMock(side_effect=[start_input, None, terminal])
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_child_workflow",
        AsyncMock(side_effect=RuntimeError("pulse child failed")),
    )
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "logger", MagicMock())
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC)
    )

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        ),
        delivery_id,
    )

    assert result == terminal
    failure_call = execute_activity.await_args_list[1]
    assert failure_call.args == (subscription_workflows.record_pulse_parent_failure,)
    assert failure_call.kwargs["task_queue"] == settings.PULSE_TASK_QUEUE
    assert failure_call.kwargs["args"] == [
        subscription_workflows.PulseStartInput(
            team_id=1,
            subscription_id=2,
            delivery_id=delivery_id,
            report_snapshot_ref=f"subscription-delivery:{delivery_id}",
            proactive_snapshot=snapshot,
        ),
        "pulse_child_failed",
    ]
    assert execute_activity.await_args_list[2].args == (
        subscription_workflows.await_existing_pulse_workflow_result,
        subscription_workflows.PulseStartInput(
            team_id=1,
            subscription_id=2,
            delivery_id=delivery_id,
            report_snapshot_ref=f"subscription-delivery:{delivery_id}",
            proactive_snapshot=snapshot,
        ),
    )
    assert execute_activity.await_args_list[2].kwargs["task_queue"] == settings.PULSE_TASK_QUEUE


@pytest.mark.asyncio
async def test_parent_returns_a_local_failure_when_durable_failure_recording_is_unavailable(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    pulse_input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=uuid4(),
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        deadline=datetime(2026, 8, 29, 12, 10, tzinfo=UTC),
        proactive_snapshot=snapshot,
    )
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_activity",
        AsyncMock(side_effect=[pulse_input, RuntimeError("record failed")]),
    )
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_child_workflow",
        AsyncMock(side_effect=RuntimeError("pulse child failed")),
    )
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "logger", MagicMock())
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC)
    )

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        ),
        delivery_id,
    )

    assert result == PulseWorkflowResult(
        pulse_run_id=pulse_input.pulse_run_id,
        status="failed",
        result_ref=f"subscriptions/pulse/runs/{pulse_input.pulse_run_id}",
        failure_code="pulse_child_failed",
    )


@pytest.mark.asyncio
async def test_parent_returns_a_deterministic_fallback_when_start_and_recording_fail(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_activity",
        AsyncMock(side_effect=[None, None, None]),
    )
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "logger", MagicMock())

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        ),
        delivery_id,
    )

    expected_run_id = subscription_workflows.uuid.uuid5(
        subscription_workflows.uuid.NAMESPACE_URL,
        f"posthog:pulse:1:2:{delivery_id}",
    )
    assert result == PulseWorkflowResult(
        pulse_run_id=expected_run_id,
        status="failed",
        result_ref=f"subscriptions/pulse/runs/{expected_run_id}",
        failure_code="pulse_child_failed",
    )


@pytest.mark.asyncio
async def test_parent_terminalizes_an_existing_child_without_a_result(monkeypatch) -> None:
    class AlreadyStartedError(Exception):
        pass

    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    pulse_input = PulseWorkflowInput(
        team_id=1,
        subscription_id=2,
        delivery_id=delivery_id,
        pulse_run_id=uuid4(),
        report_snapshot_ref=f"subscription-delivery:{delivery_id}",
        deadline=datetime(2026, 8, 29, 12, 10, tzinfo=UTC),
        proactive_snapshot=snapshot,
    )
    terminal = PulseWorkflowResult(
        pulse_run_id=pulse_input.pulse_run_id,
        status="failed",
        result_ref=f"subscriptions/pulse/runs/{pulse_input.pulse_run_id}",
        failure_code="pulse_child_failed",
    )
    monkeypatch.setattr(subscription_workflows, "WorkflowAlreadyStartedError", AlreadyStartedError)
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_activity",
        AsyncMock(side_effect=[pulse_input, None, None, terminal]),
    )
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow,
        "execute_child_workflow",
        AsyncMock(side_effect=AlreadyStartedError()),
    )
    monkeypatch.setattr(
        subscription_workflows.temporalio.workflow, "now", lambda: datetime(2026, 8, 29, 12, tzinfo=UTC)
    )
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "logger", MagicMock())

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        ),
        delivery_id,
    )

    assert result == terminal


@pytest.mark.asyncio
async def test_parent_skips_all_pulse_commands_when_snapshot_is_disabled(monkeypatch) -> None:
    execute_activity = AsyncMock()
    execute_child = AsyncMock()
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_child_workflow", execute_child)

    result = await subscription_workflows.run_pulse_before_delivery(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=ProactiveDispatchSnapshot(
                version=1, enabled=False, config_snapshot_ref="pulse-config:1"
            ),
        ),
        uuid4(),
    )

    assert result is None
    execute_activity.assert_not_awaited()
    execute_child.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_parent_prepares_the_bundle_before_its_single_delivery(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    pulse_run_id = uuid4()
    ledger_id = uuid4()
    calls: list[object] = []

    async def execute_activity(activity, *args, **kwargs):
        calls.append(activity)
        if activity is subscription_workflows.create_delivery_record:
            return delivery_id
        if activity is subscription_workflows.validate_subscription_for_delivery:
            return None
        if activity is subscription_workflows.generate_ai_subscription_report:
            return GenerateAIReportResult(target_type="email")
        if activity is subscription_workflows.prepare_pulse_delivery_bundle:
            assert kwargs["task_queue"] == settings.PULSE_TASK_QUEUE
            return SimpleNamespace(ledger_id=ledger_id)
        if activity in {subscription_workflows.deliver_subscription, subscription_workflows.deliver_subscription_v2}:
            delivery_input = args[0]
            assert delivery_input.pulse_delivery_ledger_id == ledger_id
            return DeliverSubscriptionResult()
        if activity is subscription_workflows.update_delivery_record:
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    pulse_result = PulseWorkflowResult(pulse_run_id=pulse_run_id, status="completed", result_ref="pulse-result:1")
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "patched", lambda _: False)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "info", lambda: SimpleNamespace(workflow_id="test"))
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "uuid4", uuid4)
    monkeypatch.setattr(subscription_workflows, "run_pulse_before_delivery", AsyncMock(return_value=pulse_result))

    await subscription_workflows.ProcessAISubscriptionWorkflow().run(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        )
    )

    assert calls == [
        subscription_workflows.create_delivery_record,
        subscription_workflows.validate_subscription_for_delivery,
        subscription_workflows.generate_ai_subscription_report,
        subscription_workflows.prepare_pulse_delivery_bundle,
        subscription_workflows.deliver_subscription,
        subscription_workflows.update_delivery_record,
    ]


@pytest.mark.asyncio
async def test_ai_parent_records_bundle_failure_then_delivers_the_base_report(monkeypatch) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=True, config_snapshot_ref="pulse-config:1")
    delivery_id = uuid4()
    pulse_run_id = uuid4()
    fallback_ledger_id = uuid4()
    calls: list[object] = []

    async def execute_activity(activity, *args, **kwargs):
        calls.append(activity)
        if activity is subscription_workflows.create_delivery_record:
            return delivery_id
        if activity is subscription_workflows.validate_subscription_for_delivery:
            return None
        if activity is subscription_workflows.generate_ai_subscription_report:
            return GenerateAIReportResult(target_type="email")
        if activity is subscription_workflows.prepare_pulse_delivery_bundle:
            assert kwargs["task_queue"] == settings.PULSE_TASK_QUEUE
            raise RuntimeError("object storage unavailable")
        if activity is subscription_workflows.record_pulse_delivery_bundle_preparation_failure:
            assert kwargs["task_queue"] == settings.PULSE_TASK_QUEUE
            return PulseDeliveryBundleRef(ledger_id=fallback_ledger_id)
        if activity in {subscription_workflows.deliver_subscription, subscription_workflows.deliver_subscription_v2}:
            delivery_input = args[0]
            assert delivery_input.pulse_delivery_ledger_id == fallback_ledger_id
            return DeliverSubscriptionResult()
        if activity is subscription_workflows.update_delivery_record:
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    pulse_result = PulseWorkflowResult(pulse_run_id=pulse_run_id, status="completed", result_ref="pulse-result:1")
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "patched", lambda _: False)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "info", lambda: SimpleNamespace(workflow_id="test"))
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "uuid4", uuid4)
    monkeypatch.setattr(subscription_workflows, "run_pulse_before_delivery", AsyncMock(return_value=pulse_result))

    await subscription_workflows.ProcessAISubscriptionWorkflow().run(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            proactive_snapshot=snapshot,
        )
    )

    assert calls == [
        subscription_workflows.create_delivery_record,
        subscription_workflows.validate_subscription_for_delivery,
        subscription_workflows.generate_ai_subscription_report,
        subscription_workflows.prepare_pulse_delivery_bundle,
        subscription_workflows.record_pulse_delivery_bundle_preparation_failure,
        subscription_workflows.deliver_subscription,
        subscription_workflows.update_delivery_record,
    ]


@pytest.mark.asyncio
async def test_ai_parent_without_snapshot_schedules_the_legacy_activity_sequence(monkeypatch) -> None:
    delivery_id = uuid4()
    calls: list[object] = []

    async def execute_activity(activity, *args, **kwargs):
        calls.append(activity)
        if activity is subscription_workflows.create_delivery_record:
            return delivery_id
        if activity is subscription_workflows.validate_subscription_for_delivery:
            return None
        if activity is subscription_workflows.generate_ai_subscription_report:
            return GenerateAIReportResult(target_type="email")
        if activity in {subscription_workflows.deliver_subscription, subscription_workflows.deliver_subscription_v2}:
            delivery_input = args[0]
            assert isinstance(delivery_input, dict)
            assert "pulse_delivery_ledger_id" not in delivery_input
            return DeliverSubscriptionResult()
        if activity is subscription_workflows.update_delivery_record:
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "patched", lambda _: False)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "info", lambda: SimpleNamespace(workflow_id="test"))
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "uuid4", uuid4)

    await subscription_workflows.ProcessAISubscriptionWorkflow().run(
        TrackedSubscriptionInputs(subscription_id=2, team_id=1, distinct_id="distinct")
    )

    assert calls == [
        subscription_workflows.create_delivery_record,
        subscription_workflows.validate_subscription_for_delivery,
        subscription_workflows.generate_ai_subscription_report,
        subscription_workflows.deliver_subscription,
        subscription_workflows.update_delivery_record,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("patch_active", "expects_snapshot"), [(True, True), (False, False)])
async def test_scheduled_ai_parent_loads_its_batched_snapshot_only_after_the_temporal_patch(
    monkeypatch, patch_active: bool, expects_snapshot: bool
) -> None:
    snapshot = ProactiveDispatchSnapshot(version=1, enabled=False, config_snapshot_ref="pulse-config:1")
    calls: list[object] = []

    async def execute_activity(activity, *args, **_kwargs):
        calls.append(activity)
        if activity is subscription_workflows.create_delivery_record:
            return uuid4()
        if activity is subscription_workflows.validate_subscription_for_delivery:
            return None
        if activity is subscription_workflows.load_scheduled_proactive_snapshot:
            return snapshot
        if activity is subscription_workflows.generate_ai_subscription_report:
            return GenerateAIReportResult(target_type="email")
        if activity in {subscription_workflows.deliver_subscription, subscription_workflows.deliver_subscription_v2}:
            return DeliverSubscriptionResult()
        if activity in {
            subscription_workflows.update_delivery_record,
            subscription_workflows.advance_next_delivery_date,
        }:
            return None
        raise AssertionError(f"Unexpected activity: {activity}")

    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "patched", lambda _marker: patch_active)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "info", lambda: SimpleNamespace(workflow_id="test"))
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "uuid4", uuid4)
    monkeypatch.setattr(subscription_workflows.temporalio.workflow, "logger", MagicMock())

    await subscription_workflows.ProcessAISubscriptionWorkflow().run(
        TrackedSubscriptionInputs(
            subscription_id=2,
            team_id=1,
            distinct_id="distinct",
            trigger_type=SubscriptionTriggerType.SCHEDULED,
            proactive_snapshot_manifest_ref="subscriptions/pulse/dispatch-manifests/v1/test.json",
        )
    )

    expected_calls: list[object] = [
        subscription_workflows.create_delivery_record,
        subscription_workflows.validate_subscription_for_delivery,
    ]
    if expects_snapshot:
        expected_calls.append(subscription_workflows.load_scheduled_proactive_snapshot)
    expected_calls.extend(
        [
            subscription_workflows.generate_ai_subscription_report,
            subscription_workflows.deliver_subscription_v2
            if patch_active
            else subscription_workflows.deliver_subscription,
            subscription_workflows.update_delivery_record,
            subscription_workflows.advance_next_delivery_date,
        ]
    )
    assert calls == expected_calls
