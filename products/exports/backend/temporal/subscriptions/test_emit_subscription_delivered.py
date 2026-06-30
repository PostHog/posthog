from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock, patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.activities import (
    _MAX_EVENT_SUMMARY_CHARS,
    emit_subscription_delivered_event,
)
from products.exports.backend.temporal.subscriptions.types import (
    DeliveryStatus,
    EmitSubscriptionDeliveredInputs,
    TrackedSubscriptionInputs,
)
from products.exports.backend.temporal.subscriptions.workflows import _emit_subscription_delivered
from products.product_analytics.backend.models.insight import Insight

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

PRODUCE_PATH = "products.exports.backend.temporal.subscriptions.activities.produce_internal_event"


async def _run(inputs: EmitSubscriptionDeliveredInputs):
    return await ActivityEnvironment().run(emit_subscription_delivered_event, inputs)


@sync_to_async
def _create_insight_subscription(team, user, *, change_summary: str | None) -> SubscriptionDelivery:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    subscription = Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.SLACK,
        target_value="C123|#general",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
        summary_enabled=change_summary is not None,
    )
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=team,
        status=SubscriptionDelivery.Status.COMPLETED,
        change_summary=change_summary,
        content_snapshot={},
    )


@sync_to_async
def _create_asset(team, delivery) -> int:
    asset = ExportedAsset.objects.create(
        team=team,
        insight=delivery.subscription.insight,
        export_format=ExportedAsset.ExportFormat.PNG,
    )
    return asset.id


@sync_to_async
def _create_ai_subscription(team, user, *, markdown: str) -> SubscriptionDelivery:
    subscription = Subscription.objects.create(
        team=team,
        prompt="How are we doing this week?",
        created_by=user,
        target_type=Subscription.SubscriptionTarget.SLACK,
        target_value="C123|#general",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=team,
        status=SubscriptionDelivery.Status.COMPLETED,
        content_snapshot={SubscriptionDelivery.AI_REPORT_SNAPSHOT_KEY: markdown},
    )


@pytest.mark.parametrize(
    "kind,stored_summary,expected_summary",
    [
        ("insight", "Traffic is up 12%", "Traffic is up 12%"),
        ("insight", None, None),
        ("insight", "x" * (_MAX_EVENT_SUMMARY_CHARS + 50), "x" * _MAX_EVENT_SUMMARY_CHARS),
        ("ai", "# Weekly report\nAll good.", "# Weekly report\nAll good."),
        ("ai", "", None),
    ],
)
async def test_emit_resolves_and_caps_summary_per_resource_type(
    team, user, kind: str, stored_summary: str | None, expected_summary: str | None
) -> None:
    if kind == "ai":
        delivery = await _create_ai_subscription(team, user, markdown=stored_summary or "")
        expected_resource = "ai_prompt"
    else:
        delivery = await _create_insight_subscription(team, user, change_summary=stored_summary)
        expected_resource = "insight"

    with patch(PRODUCE_PATH) as mock_produce:
        await _run(
            EmitSubscriptionDeliveredInputs(
                subscription_id=delivery.subscription_id,
                team_id=team.id,
                delivery_id=delivery.id,
                trigger_type="scheduled",
                recipient_count=1,
                successful_asset_ids=[],
            )
        )

    mock_produce.assert_called_once()
    props = mock_produce.call_args.kwargs["event"].properties
    assert props["resource_type"] == expected_resource
    assert props["summary"] == expected_summary


async def test_emit_for_insight_subscription_reuses_asset_urls(team, user) -> None:
    delivery = await _create_insight_subscription(team, user, change_summary="Traffic is up 12%")
    asset_id = await _create_asset(team, delivery)

    with patch(PRODUCE_PATH) as mock_produce:
        await _run(
            EmitSubscriptionDeliveredInputs(
                subscription_id=delivery.subscription_id,
                team_id=team.id,
                delivery_id=delivery.id,
                trigger_type="scheduled",
                recipient_count=2,
                successful_asset_ids=[asset_id],
            )
        )

    event = mock_produce.call_args.kwargs["event"]
    assert event.event == "$subscription_delivered"
    assert event.uuid == str(delivery.id)
    props = event.properties
    assert props["target_type"] == Subscription.SubscriptionTarget.SLACK
    assert props["recipient_count"] == 2
    assert len(props["asset_urls"]) == 1
    assert "/exporter/" in props["asset_urls"][0]


async def test_emit_for_ai_subscription_has_no_assets(team, user) -> None:
    delivery = await _create_ai_subscription(team, user, markdown="# Weekly report")

    with patch(PRODUCE_PATH) as mock_produce:
        await _run(
            EmitSubscriptionDeliveredInputs(
                subscription_id=delivery.subscription_id,
                team_id=team.id,
                delivery_id=delivery.id,
                trigger_type="scheduled",
                recipient_count=1,
                successful_asset_ids=[],
            )
        )

    props = mock_produce.call_args.kwargs["event"].properties
    assert props["asset_urls"] == []
    assert props["insight_short_id"] is None


async def test_emit_swallows_errors_for_missing_records(team) -> None:
    # Best-effort: a non-existent subscription/delivery must be logged and swallowed, never raised,
    # and must not emit a (malformed) event.
    with patch(PRODUCE_PATH) as mock_produce:
        await _run(
            EmitSubscriptionDeliveredInputs(
                subscription_id=999_999,
                team_id=team.id,
                delivery_id=uuid4(),
                trigger_type="scheduled",
                recipient_count=0,
                successful_asset_ids=[],
            )
        )

    mock_produce.assert_not_called()


@pytest.mark.parametrize(
    "final_status,delivery_id_present,should_emit",
    [
        (DeliveryStatus.COMPLETED, True, True),
        (DeliveryStatus.FAILED, True, False),
        (DeliveryStatus.SKIPPED, True, False),
        (DeliveryStatus.COMPLETED, False, False),
    ],
)
async def test_emit_helper_only_fires_on_completed_delivery(
    final_status: str, delivery_id_present: bool, should_emit: bool
) -> None:
    # The COMPLETED gate lives in the helper so both workflows call it unconditionally; verify the
    # gate (and that the right inputs flow through) without standing up a full workflow environment.
    inputs = TrackedSubscriptionInputs(subscription_id=1, team_id=2, trigger_type="scheduled")
    delivery_id = uuid4() if delivery_id_present else None

    with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_execute:
        await _emit_subscription_delivered(inputs, final_status, delivery_id, 3, [10, 11])

    if should_emit:
        mock_execute.assert_called_once()
        activity, activity_inputs = mock_execute.call_args.args[0], mock_execute.call_args.args[1]
        assert activity is emit_subscription_delivered_event
        assert activity_inputs.delivery_id == delivery_id
        assert activity_inputs.recipient_count == 3
        assert activity_inputs.successful_asset_ids == [10, 11]
    else:
        mock_execute.assert_not_called()
