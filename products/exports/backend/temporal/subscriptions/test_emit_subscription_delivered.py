from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.activities import emit_subscription_delivered_event
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import AI_REPORT_SNAPSHOT_KEY
from products.exports.backend.temporal.subscriptions.types import EmitSubscriptionDeliveredInputs
from products.product_analytics.backend.models.insight import Insight

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


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
        content_snapshot={AI_REPORT_SNAPSHOT_KEY: markdown},
    )


async def test_emit_for_insight_subscription_includes_summary_and_asset_urls(team, user) -> None:
    delivery = await _create_insight_subscription(team, user, change_summary="Traffic is up 12%")
    asset_id = await _create_asset(team, delivery)

    with patch("products.exports.backend.temporal.subscriptions.activities.produce_internal_event") as mock_produce:
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

    mock_produce.assert_called_once()
    kwargs = mock_produce.call_args.kwargs
    assert kwargs["team_id"] == team.id
    event = kwargs["event"]
    assert event.event == "$subscription_delivered"
    assert event.uuid == f"subscription_delivered:{delivery.id}"
    props = event.properties
    assert props["resource_type"] == "insight"
    assert props["target_type"] == Subscription.SubscriptionTarget.SLACK
    assert props["summary"] == "Traffic is up 12%"
    assert props["recipient_count"] == 2
    assert len(props["asset_urls"]) == 1
    assert "/exporter/" in props["asset_urls"][0]


async def test_emit_for_ai_subscription_uses_report_markdown_and_no_assets(team, user) -> None:
    delivery = await _create_ai_subscription(team, user, markdown="# Weekly report\nAll good.")

    with patch("products.exports.backend.temporal.subscriptions.activities.produce_internal_event") as mock_produce:
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
    assert props["resource_type"] == "ai_prompt"
    assert props["summary"] == "# Weekly report\nAll good."
    assert props["asset_urls"] == []
    assert props["insight_short_id"] is None
