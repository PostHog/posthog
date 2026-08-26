import uuid

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
    deliver_subscription,
    deliver_subscription_v2,
    update_delivery_record,
    validate_subscription_for_delivery,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import generate_ai_subscription_report
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import (
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportResult,
    SnapshotInsightsResult,
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
