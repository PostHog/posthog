import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_slack_response import AsyncSlackResponse
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.email import EmailDeliveryError
from posthog.models.integration import Integration
from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.temporal.exports.activities import export_asset_activity
from posthog.temporal.exports.types import ExportAssetResult

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import SubscriptionDelivery
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
from products.exports.backend.temporal.subscriptions.delivery_common import deliver_slack
from products.exports.backend.temporal.subscriptions.snapshot_activities import snapshot_subscription_insights
from products.exports.backend.temporal.subscriptions.types import (
    CreateExportAssetsResult,
    DeliverSubscriptionInputs,
    DeliverSubscriptionResult,
    GenerateAIReportResult,
    RecipientResult,
    SnapshotInsightsResult,
    SubscriptionTriggerType,
    TrackedSubscriptionInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import (
    ProcessAISubscriptionWorkflow,
    ProcessSubscriptionWorkflow,
)
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.subscriptions.slack_subscriptions import SlackDeliveryResult, _claim_slack_gallery_delivery
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def test_deliver_slack_records_unconfirmed_gallery_without_retry(team, user) -> None:
    integration = await sync_to_async(Integration.objects.create)(team=team, kind="slack", config={})
    subscription = await sync_to_async(create_subscription)(
        team=team,
        created_by=user,
        target_type="slack",
        target_value="C123|#general",
        integration=integration,
    )
    send = AsyncMock(
        return_value=SlackDeliveryResult(
            main_message_sent=False,
            total_thread_messages=0,
            failed_thread_message_indices=[],
            failure_message="Slack could not confirm whether the gallery was delivered.",
            failure_type="slack_delivery_unconfirmed",
        )
    )

    with patch(
        "products.exports.backend.temporal.subscriptions.delivery_common._capture_delivery_failed_event"
    ) as capture_failed:
        result = await deliver_slack(subscription, [], send)

    send.assert_awaited_once_with(integration)
    capture_failed.assert_called_once()
    assert result.recipient_results[0].status == "failed"
    assert result.recipient_results[0].error == {
        "message": "Slack could not confirm whether the gallery was delivered.",
        "type": "slack_delivery_unconfirmed",
    }


async def test_claim_slack_gallery_delivery_is_atomic(team, user) -> None:
    subscription = await sync_to_async(create_subscription)(
        team=team,
        created_by=user,
        target_type="slack",
        target_value="C123|#general",
    )
    delivery = await sync_to_async(SubscriptionDelivery.objects.create)(
        subscription=subscription,
        team=team,
        temporal_workflow_id="workflow-claim",
        idempotency_key="gallery-claim",
        trigger_type="scheduled",
        target_type="slack",
        target_value=subscription.target_value,
    )

    assert await sync_to_async(_claim_slack_gallery_delivery)(delivery.id) is True
    assert await sync_to_async(_claim_slack_gallery_delivery)(delivery.id) is False
    await sync_to_async(delivery.refresh_from_db)()
    assert delivery.slack_gallery_delivery_started_at is not None


@pytest.mark.parametrize(
    "slack_error_code",
    [
        "file_uploads_disabled",
        "file_upload_size_restricted",
        "file_type_not_allowed",
        "storage_limit_reached",
        "ekm_access_denied",
    ],
)
async def test_deliver_slack_auto_disables_permanent_gallery_errors(team, user, slack_error_code) -> None:
    integration = await sync_to_async(Integration.objects.create)(team=team, kind="slack", config={})
    subscription = await sync_to_async(create_subscription)(
        team=team,
        created_by=user,
        target_type="slack",
        target_value="C123|#general",
        integration=integration,
    )
    response = AsyncSlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/files.completeUploadExternal",
        req_args={},
        data={"ok": False, "error": slack_error_code},
        headers={},
        status_code=200,
    )
    send = AsyncMock(side_effect=SlackApiError("Error", response))
    delivery = await sync_to_async(SubscriptionDelivery.objects.create)(
        subscription=subscription,
        team=team,
        temporal_workflow_id=f"workflow-{slack_error_code}",
        idempotency_key=f"gallery-error-{slack_error_code}",
        trigger_type="scheduled",
        target_type="slack",
        target_value=subscription.target_value,
    )

    with (
        patch("products.exports.backend.temporal.subscriptions.delivery_common._capture_delivery_failed_event"),
        patch("ee.tasks.subscriptions.auto_disable.create_subscription_auto_disabled_notification"),
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription"),
    ):
        result = await deliver_slack(subscription, [], send, delivery_id=delivery.id)

    await sync_to_async(subscription.refresh_from_db)()
    await sync_to_async(delivery.refresh_from_db)()
    assert subscription.enabled is False
    assert result.recipient_results[0].error == {
        "message": "Slack file uploads are unavailable for this workspace",
        "type": "slack_file_upload_unavailable",
    }
    assert delivery.recipient_results == [
        {
            "recipient": subscription.target_value,
            "status": "failed",
            "error": {
                "message": "Slack file uploads are unavailable for this workspace",
                "type": "slack_file_upload_unavailable",
            },
            "human_readable_error": "Slack file uploads are unavailable for this workspace",
        }
    ]


async def test_disabled_activity_retry_returns_persisted_permanent_failure(team, user) -> None:
    integration = await sync_to_async(Integration.objects.create)(team=team, kind="slack", config={})
    subscription = await sync_to_async(create_subscription)(
        team=team,
        created_by=user,
        target_type="slack",
        target_value="C123|#general",
        integration=integration,
    )
    delivery = await sync_to_async(SubscriptionDelivery.objects.create)(
        subscription=subscription,
        team=team,
        temporal_workflow_id="workflow-disabled-retry",
        idempotency_key="gallery-disabled-retry",
        trigger_type="scheduled",
        target_type="slack",
        target_value=subscription.target_value,
    )
    response = AsyncSlackResponse(
        client=None,
        http_verb="POST",
        api_url="https://slack.com/api/files.completeUploadExternal",
        req_args={},
        data={"ok": False, "error": "file_uploads_disabled"},
        headers={},
        status_code=200,
    )

    with (
        patch("products.exports.backend.temporal.subscriptions.delivery_common._capture_delivery_failed_event"),
        patch("ee.tasks.subscriptions.auto_disable.create_subscription_auto_disabled_notification"),
        patch("ee.tasks.subscriptions.auto_disable.send_notifications_for_disabled_subscription"),
    ):
        await deliver_slack(
            subscription,
            [],
            AsyncMock(side_effect=SlackApiError("Error", response)),
            delivery_id=delivery.id,
        )

    replay_result = await ActivityEnvironment().run(
        deliver_subscription_v2,
        DeliverSubscriptionInputs(
            subscription_id=subscription.id,
            exported_asset_ids=[],
            total_insight_count=0,
            delivery_id=delivery.id,
        ),
    )

    assert len(replay_result.recipient_results) == 1
    assert replay_result.recipient_results[0].status == "failed"
    assert replay_result.recipient_results[0].error == {
        "message": "Slack file uploads are unavailable for this workspace",
        "type": "slack_file_upload_unavailable",
    }


async def test_deliver_slack_records_omitted_gallery_attachments_as_partial(team, user) -> None:
    integration = await sync_to_async(Integration.objects.create)(team=team, kind="slack", config={})
    subscription = await sync_to_async(create_subscription)(
        team=team,
        created_by=user,
        target_type="slack",
        target_value="C123|#general",
        integration=integration,
    )
    send = AsyncMock(
        return_value=SlackDeliveryResult(
            main_message_sent=True,
            total_thread_messages=0,
            failed_thread_message_indices=[],
            omitted_attachment_count=2,
        )
    )

    result = await deliver_slack(subscription, [], send)

    assert result.recipient_results[0].status == "partial"
    assert result.recipient_results[0].error == {
        "message": "2 images could not be attached",
        "type": "partial_attachment_failure",
    }
    assert result.recipient_results[0].human_readable_error == "2 images could not be attached"


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
@pytest.mark.parametrize("recipient_status", [None, "failed", "partial"])
async def test_process_subscription_picks_delivery_activity_from_patch(patch_active, recipient_status) -> None:
    picked = None
    delivery_retry_policy = None

    async def fake_execute_activity(activity, inputs, **_kwargs):
        nonlocal delivery_retry_policy, picked
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
            delivery_retry_policy = _kwargs["retry_policy"]
            return DeliverSubscriptionResult(
                recipient_results=(
                    [
                        RecipientResult(
                            recipient="C123|#general",
                            status=recipient_status,
                            error={
                                "message": "Slack delivery was degraded",
                                "type": (
                                    "slack_delivery_unconfirmed"
                                    if recipient_status == "failed"
                                    else "partial_attachment_failure"
                                ),
                            },
                        )
                    ]
                    if recipient_status is not None
                    else []
                )
            )
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
    assert delivery_retry_policy is not None
    assert delivery_retry_policy.maximum_attempts == 5
    assert inputs.slo is not None
    assert inputs.slo.completion_properties["target_type"] == "email"
    assert inputs.slo.completion_properties["selected_insight_count"] == 4
    assert inputs.slo.completion_properties["available_insight_count"] == 5
    if recipient_status == "failed":
        assert inputs.slo.outcome == SloOutcome.FAILURE
        assert inputs.slo.completion_properties["error_type"] == "slack_delivery_unconfirmed"
    elif recipient_status == "partial":
        assert inputs.slo.outcome == SloOutcome.FAILURE
        assert inputs.slo.completion_properties["partial_delivery"] is True


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
