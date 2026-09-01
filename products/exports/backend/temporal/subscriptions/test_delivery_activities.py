import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.email import EmailDeliveryError
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.types import ExportAssetResult

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.temporal.subscriptions.activities import (
    advance_next_delivery_date,
    create_delivery_record,
    create_export_assets,
    create_scheduled_delivery_record,
    deliver_subscription,
    deliver_subscription_v2,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import (
    CreateDeliveryRecordInputs,
    CreateExportAssetsResult,
    CreateScheduledDeliveryRecordResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportResult,
    SnapshotInsightsResult,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import (
    ProcessAISubscriptionWorkflow,
    ProcessSubscriptionWorkflow,
)
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


# v1 only exists as a Temporal history-compat shim for pre-patch workflows. Both
# entry points must hit the shared delivery + EmailDeliveryError -> non-retryable
# ApplicationError mapping, so the delivery record keeps per-recipient results.
@pytest.mark.parametrize("activity", [deliver_subscription, deliver_subscription_v2])
async def test_deliver_subscription_wraps_email_delivery_error(team, user, activity) -> None:
    insight = await sync_to_async(Insight.objects.create)(team=team, short_id="covdg", name="Coverage delegation")
    asset = await sync_to_async(ExportedAsset.objects.create)(
        team=team, insight=insight, export_format="image/png", content_location="s3://bucket/cov.png"
    )
    subscription = await sync_to_async(create_subscription)(team=team, insight=insight, created_by=user)
    inputs = DeliverSubscriptionInputs(
        subscription_id=subscription.id,
        exported_asset_ids=[asset.id],
        total_insight_count=1,
    )

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.activities.send_email_subscription_report",
            side_effect=EmailDeliveryError("provider rejected delivery"),
        ),
        patch("products.exports.backend.temporal.subscriptions.delivery_common._capture_delivery_failed_event"),
    ):
        with pytest.raises(ApplicationError) as error:
            await ActivityEnvironment().run(activity, inputs)

    assert error.value.non_retryable is True
    assert error.value.details[0]["recipient_results"][0]["status"] == "failed"


# The patch-gated activity switch is the rollout seam for the v2 delivery campaign: new
# executions take v2, in-flight pre-patch executions stay on v1 for history compatibility.
# Driving through the workflow (not just the patched() helper) pins both the selection and
# that the chosen activity is what execute_activity receives.
@pytest.mark.parametrize("patch_active", [True, False], ids=["patched_v2", "pre_patch_v1"])
async def test_process_subscription_picks_delivery_activity_from_patch(patch_active) -> None:
    picked = None

    async def fake_execute_activity(activity, inputs, **_kwargs):
        nonlocal picked
        if activity is create_delivery_record:
            return uuid.uuid4()
        if activity is validate_subscription_for_delivery:
            return None
        if activity is create_export_assets:
            return CreateExportAssetsResult(
                exported_asset_ids=[1],
                total_insight_count=3,
                target_type="email",
                available_insight_count=5,
                selected_insight_count=4,
            )
        if activity is export_asset_activity:
            return ExportAssetResult(exported_asset_id=1, success=True)
        if activity is snapshot_subscription_insights:
            return SnapshotInsightsResult()
        if activity in (deliver_subscription, deliver_subscription_v2):
            picked = activity
            return DeliverSubscriptionResult()
        if activity is update_delivery_record:
            return None
        raise AssertionError(f"unexpected activity {activity}")

    with (
        patch("temporalio.workflow.execute_activity", side_effect=fake_execute_activity),
        patch("temporalio.workflow.patched", return_value=patch_active),
        patch("temporalio.workflow.info") as mock_info,
        patch("temporalio.workflow.uuid4", return_value=uuid.uuid4()),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mock_info.return_value = MagicMock(workflow_id="wf-test")
        inputs = TrackedSubscriptionInputs(
            subscription_id=1,
            team_id=1,
            distinct_id="u1",
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=1,
                resource_id="1",
                distinct_id="u1",
            ),
        )
        await ProcessSubscriptionWorkflow().run(inputs)

    assert picked is (deliver_subscription_v2 if patch_active else deliver_subscription)
    assert inputs.slo is not None
    assert inputs.slo.completion_properties["target_type"] == "email"
    assert inputs.slo.completion_properties["selected_insight_count"] == 4
    assert inputs.slo.completion_properties["available_insight_count"] == 5


@pytest.mark.parametrize("patch_active", [True, False], ids=["patched_v2", "pre_patch_v1"])
async def test_process_ai_subscription_picks_delivery_activity_from_patch(patch_active) -> None:
    picked = None

    async def fake_execute_activity(activity, inputs, **_kwargs):
        nonlocal picked
        if activity is create_delivery_record:
            return uuid.uuid4()
        if activity is validate_subscription_for_delivery:
            return None
        if activity is generate_ai_subscription_report:
            return GenerateAIReportResult(target_type="slack")
        if activity in (deliver_subscription, deliver_subscription_v2):
            picked = activity
            return DeliverSubscriptionResult()
        if activity in (update_delivery_record, advance_next_delivery_date):
            return None
        raise AssertionError(f"unexpected activity {activity}")

    with (
        patch("temporalio.workflow.execute_activity", side_effect=fake_execute_activity),
        patch("temporalio.workflow.patched", return_value=patch_active),
        patch("temporalio.workflow.info") as mock_info,
        patch("temporalio.workflow.uuid4", return_value=uuid.uuid4()),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mock_info.return_value = MagicMock(workflow_id="wf-test-ai")
        inputs = TrackedSubscriptionInputs(
            subscription_id=1,
            team_id=1,
            distinct_id="u1",
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=1,
                resource_id="1",
                distinct_id="u1",
            ),
        )
        await ProcessAISubscriptionWorkflow().run(inputs)

    assert picked is (deliver_subscription_v2 if patch_active else deliver_subscription)
    assert inputs.slo is not None
    assert inputs.slo.completion_properties["target_type"] == "slack"


@pytest.mark.parametrize(
    "workflow_type",
    [ProcessSubscriptionWorkflow, ProcessAISubscriptionWorkflow],
    ids=["standard", "ai"],
)
async def test_scheduled_delivery_skips_duplicate_occurrence_without_advancing_again(
    workflow_type: type[ProcessSubscriptionWorkflow] | type[ProcessAISubscriptionWorkflow],
) -> None:
    activities: list[object] = []

    async def fake_execute_activity(activity: object, _inputs: object = None, **_kwargs: object) -> object:
        activities.append(activity)
        if activity is create_scheduled_delivery_record:
            return CreateScheduledDeliveryRecordResult(delivery_id=uuid.uuid4(), created=False)
        raise AssertionError(f"unexpected activity {activity}")

    with (
        patch("temporalio.workflow.execute_activity", side_effect=fake_execute_activity),
        patch("temporalio.workflow.info") as mock_info,
        patch(
            "temporalio.workflow.patched",
            side_effect=lambda patch_id: patch_id == "subscription-scheduled-delivery-dedupe-2026-09",
        ),
        patch("temporalio.workflow.uuid4", return_value=uuid.uuid4()),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mock_info.return_value = MagicMock(workflow_id="wf-test")
        await workflow_type().run(
            TrackedSubscriptionInputs(
                subscription_id=1,
                team_id=1,
                distinct_id="u1",
                trigger_type=SubscriptionTriggerType.SCHEDULED,
                scheduled_at="2026-09-01T09:30:00+00:00",
            )
        )

    assert activities == [create_scheduled_delivery_record]


@pytest.mark.parametrize(
    "workflow_type",
    [ProcessSubscriptionWorkflow, ProcessAISubscriptionWorkflow],
    ids=["standard", "ai"],
)
async def test_scheduled_record_failure_advances_schedule_and_propagates(
    workflow_type: type[ProcessSubscriptionWorkflow] | type[ProcessAISubscriptionWorkflow],
) -> None:
    record_error = RuntimeError("record creation failed")
    activities: list[object] = []

    async def fake_execute_activity(activity: object, _inputs: object = None, **_kwargs: object) -> object:
        activities.append(activity)
        if activity is create_scheduled_delivery_record:
            raise record_error
        if activity is advance_next_delivery_date:
            return None
        raise AssertionError(f"unexpected activity {activity}")

    slo = SloConfig(
        operation=SloOperation.SUBSCRIPTION_DELIVERY,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=1,
        resource_id="1",
        distinct_id="u1",
    )
    with (
        patch("temporalio.workflow.execute_activity", side_effect=fake_execute_activity),
        patch(
            "temporalio.workflow.patched",
            side_effect=lambda patch_id: patch_id == "subscription-scheduled-delivery-dedupe-2026-09",
        ),
        patch("temporalio.workflow.info") as mock_info,
        patch("temporalio.workflow.uuid4", return_value=uuid.uuid4()),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mock_info.return_value = MagicMock(workflow_id="wf-test")
        with pytest.raises(RuntimeError, match="record creation failed") as exc_info:
            await workflow_type().run(
                TrackedSubscriptionInputs(
                    subscription_id=1,
                    team_id=1,
                    distinct_id="u1",
                    trigger_type=SubscriptionTriggerType.SCHEDULED,
                    scheduled_at="2026-09-01T09:30:00+00:00",
                    slo=slo,
                )
            )

    assert exc_info.value is record_error
    assert activities == [create_scheduled_delivery_record, advance_next_delivery_date]
    assert slo.completion_properties["failure_stage"] == "delivery_record"


async def test_create_scheduled_delivery_record_reconciles_duplicate_once(team, user) -> None:
    scheduled_at = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)
    subscription = await sync_to_async(create_subscription)(team=team, created_by=user)
    subscription.next_delivery_date = scheduled_at
    await sync_to_async(subscription.save)(update_fields=["next_delivery_date"])
    first_inputs = CreateDeliveryRecordInputs(
        subscription_id=subscription.id,
        team_id=team.id,
        temporal_workflow_id="first-sweep",
        idempotency_key="first-sweep-run",
        trigger_type=SubscriptionTriggerType.SCHEDULED,
        scheduled_at=scheduled_at.isoformat(),
    )

    first_result = await create_scheduled_delivery_record(first_inputs)
    assert first_result.created is True

    retry_result = await create_scheduled_delivery_record(first_inputs)
    assert retry_result == first_result

    duplicate_result = await create_scheduled_delivery_record(
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            temporal_workflow_id="second-sweep",
            idempotency_key="second-sweep-run",
            trigger_type=SubscriptionTriggerType.SCHEDULED,
            scheduled_at=scheduled_at.isoformat(),
        )
    )
    assert duplicate_result.delivery_id == first_result.delivery_id
    assert duplicate_result.created is False
    await sync_to_async(subscription.refresh_from_db)()
    next_delivery_date = subscription.next_delivery_date
    assert next_delivery_date is not None and next_delivery_date > scheduled_at

    await create_scheduled_delivery_record(
        CreateDeliveryRecordInputs(
            subscription_id=subscription.id,
            team_id=team.id,
            temporal_workflow_id="third-sweep",
            idempotency_key="third-sweep-run",
            trigger_type=SubscriptionTriggerType.SCHEDULED,
            scheduled_at=scheduled_at.isoformat(),
        )
    )
    await sync_to_async(subscription.refresh_from_db)()
    assert subscription.next_delivery_date == next_delivery_date


@pytest.mark.parametrize(
    "workflow_type",
    [ProcessSubscriptionWorkflow, ProcessAISubscriptionWorkflow],
    ids=["standard", "ai"],
)
async def test_schedule_update_failure_preserves_primary_failure(
    workflow_type: type[ProcessSubscriptionWorkflow] | type[ProcessAISubscriptionWorkflow],
) -> None:
    primary_error = RuntimeError("delivery failed")
    schedule_error = RuntimeError("schedule update failed")

    async def fake_execute_activity(activity: object, _inputs: object, **_kwargs: object) -> object:
        if activity is create_delivery_record:
            return uuid.uuid4()
        if activity is validate_subscription_for_delivery:
            return None
        if activity is create_export_assets:
            return CreateExportAssetsResult(exported_asset_ids=[1], total_insight_count=1)
        if activity is export_asset_activity:
            return ExportAssetResult(exported_asset_id=1, success=True)
        if activity is snapshot_subscription_insights:
            return SnapshotInsightsResult()
        if activity is generate_ai_subscription_report:
            return GenerateAIReportResult()
        if activity in (deliver_subscription, deliver_subscription_v2):
            raise primary_error
        if activity is update_delivery_record:
            return None
        if activity is advance_next_delivery_date:
            raise schedule_error
        raise AssertionError(f"unexpected activity {activity}")

    with (
        patch("temporalio.workflow.execute_activity", side_effect=fake_execute_activity),
        patch("temporalio.workflow.patched", return_value=False),
        patch("temporalio.workflow.info") as mock_info,
        patch("temporalio.workflow.uuid4", return_value=uuid.uuid4()),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mock_info.return_value = MagicMock(workflow_id="wf-test")
        inputs = TrackedSubscriptionInputs(
            subscription_id=1,
            team_id=1,
            distinct_id="u1",
            trigger_type=SubscriptionTriggerType.SCHEDULED,
            slo=SloConfig(
                operation=SloOperation.SUBSCRIPTION_DELIVERY,
                area=SloArea.ANALYTIC_PLATFORM,
                team_id=1,
                resource_id="1",
                distinct_id="u1",
            ),
        )

        with pytest.raises(RuntimeError, match="delivery failed") as exc_info:
            await workflow_type().run(inputs)

    assert exc_info.value is primary_error
    assert inputs.slo is not None
    assert inputs.slo.completion_properties["failure_stage"] == "delivery"
    assert inputs.slo.completion_properties["failure_component"] == "subscription_delivery"
