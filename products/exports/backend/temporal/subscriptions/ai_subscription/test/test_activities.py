from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from asgiref.sync import sync_to_async

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.activities import (
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    _persist_ai_report,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.report_pipeline import (
    AiReportResult,
    QueryStepDiagnostic,
)
from products.product_analytics.backend.models.insight import Insight

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@sync_to_async
def _create_delivery(team, user) -> SubscriptionDelivery:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    subscription = Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=team,
        status=SubscriptionDelivery.Status.STARTING,
        content_snapshot={},
    )


@sync_to_async
def _snapshot(delivery_id) -> dict:
    return SubscriptionDelivery.objects.values_list("content_snapshot", flat=True).get(pk=delivery_id)


async def test_persist_ai_report_writes_markdown_and_query_diagnostics(team, user) -> None:
    delivery = await _create_delivery(team, user)

    await _persist_ai_report(
        delivery.id,
        AiReportResult(
            markdown="# Weekly report",
            diagnostics=(
                QueryStepDiagnostic(description="adoption", hogql="SELECT count()", ok=True, error_type=None),
                QueryStepDiagnostic(
                    description="reliability", hogql="SELECT bad", ok=False, error_type="ResolutionError"
                ),
            ),
        ),
    )

    snapshot = await _snapshot(delivery.id)
    assert snapshot[AI_REPORT_SNAPSHOT_KEY] == "# Weekly report"
    assert snapshot[AI_REPORT_DIAGNOSTICS_KEY] == [
        {"description": "adoption", "hogql": "SELECT count()", "ok": True, "error_type": None},
        {"description": "reliability", "hogql": "SELECT bad", "ok": False, "error_type": "ResolutionError"},
    ]
