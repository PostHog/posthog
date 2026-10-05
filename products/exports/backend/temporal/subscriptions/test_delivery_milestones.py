import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from products.exports.backend.models.subscription import Subscription, SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.delivery_milestones import (
    FIRST_DELIVERY_COMPLETED_PERSON_PROPERTY,
    record_first_delivery_completed,
)
from products.product_analytics.backend.facade.models import Insight

pytestmark = [pytest.mark.django_db]

SUCCESS_RESULTS = [{"recipient": "test@posthog.com", "status": "success", "error": None}]
FAILED_RESULTS = [{"recipient": "test@posthog.com", "status": "failed", "error": "bounced"}]


def _create_subscription(team, user) -> Subscription:
    insight = Insight.objects.create(team=team, name="Pageviews", created_by=user)
    return Subscription.objects.create(
        team=team,
        insight=insight,
        created_by=user,
        target_type=Subscription.SubscriptionTarget.EMAIL,
        target_value="test@posthog.com",
        frequency=Subscription.SubscriptionFrequency.WEEKLY,
        start_date=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
    )


def _create_delivery(subscription: Subscription, *, status: str, recipient_results: list[dict], finished_at=None):
    return SubscriptionDelivery.objects.create(
        subscription=subscription,
        team=subscription.team,
        status=status,
        recipient_results=recipient_results,
        finished_at=finished_at,
        idempotency_key=str(uuid.uuid4()),
    )


@pytest.mark.parametrize(
    "preceding_results",
    [
        pytest.param(None, id="no_preceding_delivery"),
        pytest.param(FAILED_RESULTS, id="after_a_completed_delivery_that_reached_nobody"),
    ],
)
def test_stamps_the_creator_when_the_first_delivery_reaches_a_recipient(
    team, user, fake_ph_client, preceding_results
) -> None:
    subscription = _create_subscription(team, user)
    if preceding_results is not None:
        _create_delivery(
            subscription,
            status=SubscriptionDelivery.Status.COMPLETED,
            recipient_results=preceding_results,
            finished_at=datetime(2022, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")),
        )
    finished_at = datetime(2022, 1, 8, 9, 0, tzinfo=ZoneInfo("UTC"))
    delivery = _create_delivery(
        subscription,
        status=SubscriptionDelivery.Status.COMPLETED,
        recipient_results=SUCCESS_RESULTS,
        finished_at=finished_at,
    )

    record_first_delivery_completed(delivery.id)

    assert len(fake_ph_client.captured) == 1
    captured = fake_ph_client.captured[0]
    assert captured["distinct_id"] == user.distinct_id
    assert captured["properties"]["$set_once"] == {FIRST_DELIVERY_COMPLETED_PERSON_PROPERTY: finished_at.isoformat()}


@pytest.mark.parametrize(
    "status,recipient_results,earlier_delivery",
    [
        pytest.param(SubscriptionDelivery.Status.STARTING, SUCCESS_RESULTS, False, id="still_running"),
        pytest.param(SubscriptionDelivery.Status.FAILED, FAILED_RESULTS, False, id="failed"),
        pytest.param(SubscriptionDelivery.Status.COMPLETED, [], False, id="no_recipients"),
        pytest.param(SubscriptionDelivery.Status.COMPLETED, FAILED_RESULTS, False, id="every_recipient_failed"),
        pytest.param(SubscriptionDelivery.Status.COMPLETED, SUCCESS_RESULTS, True, id="not_the_first_delivery"),
    ],
)
def test_does_not_stamp_the_creator(team, user, fake_ph_client, status, recipient_results, earlier_delivery) -> None:
    subscription = _create_subscription(team, user)
    if earlier_delivery:
        _create_delivery(
            subscription,
            status=SubscriptionDelivery.Status.COMPLETED,
            recipient_results=SUCCESS_RESULTS,
            finished_at=datetime(2022, 1, 8, 9, 0, tzinfo=ZoneInfo("UTC")),
        )
    delivery = _create_delivery(
        subscription,
        status=status,
        recipient_results=recipient_results,
        finished_at=datetime(2022, 1, 15, 9, 0, tzinfo=ZoneInfo("UTC")),
    )

    record_first_delivery_completed(delivery.id)

    assert fake_ph_client.captured == []
