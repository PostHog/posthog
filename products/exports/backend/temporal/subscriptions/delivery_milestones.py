import uuid
from typing import Any

from structlog import get_logger

from posthog.ph_client import ph_scoped_capture

from products.exports.backend.models.subscription import SubscriptionDelivery

LOGGER = get_logger(__name__)

FIRST_DELIVERY_COMPLETED_EVENT = "subscription_first_delivery_completed"
FIRST_DELIVERY_COMPLETED_PERSON_PROPERTY = "subscription_first_delivery_completed"


def _reached_a_recipient(delivery: SubscriptionDelivery) -> bool:
    results = delivery.recipient_results
    if not isinstance(results, list):
        return False
    return any(isinstance(result, dict) and result.get("status") == "success" for result in results)


def record_first_delivery_completed(delivery_id: uuid.UUID) -> None:
    """Stamp the creator with the time their subscription first reached a recipient.

    Surfaces that must wait until someone can judge a real delivery read the person
    property — the subscriptions feedback survey is the current one. The value is a
    timestamp, not a flag, so such a surface can also require a minimum age without
    a second instrumentation change.
    """
    delivery = (
        SubscriptionDelivery.objects.select_related("subscription__created_by", "subscription__team")
        .filter(pk=delivery_id, status=SubscriptionDelivery.Status.COMPLETED)
        .first()
    )
    if delivery is None or not _reached_a_recipient(delivery):
        return

    subscription = delivery.subscription
    creator = subscription.created_by
    if creator is None or not creator.distinct_id:
        return

    # A completed delivery whose recipients all failed is not a milestone, so it must not
    # block a later delivery that did reach someone.
    another_delivery_reached_a_recipient = (
        SubscriptionDelivery.objects.filter(
            subscription_id=subscription.id,
            team_id=delivery.team_id,
            status=SubscriptionDelivery.Status.COMPLETED,
            recipient_results__contains=[{"status": "success"}],
        )
        .exclude(pk=delivery.pk)
        .exists()
    )
    if another_delivery_reached_a_recipient:
        return

    completed_at = delivery.finished_at or delivery.last_updated_at
    properties: dict[str, Any] = {
        "subscription_id": subscription.id,
        "team_id": delivery.team_id,
        "delivery_id": str(delivery.id),
        "target_type": delivery.target_type,
        "resource_type": subscription.resource_type,
        # $set_once keeps the first delivery as the recorded one when a retry replays this activity.
        "$set_once": {FIRST_DELIVERY_COMPLETED_PERSON_PROPERTY: completed_at.isoformat()},
    }
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=creator.distinct_id,
            event=FIRST_DELIVERY_COMPLETED_EVENT,
            properties=properties,
            groups={"organization": str(subscription.team.organization_id)},
        )
    LOGGER.info(
        "record_first_delivery_completed.captured",
        subscription_id=subscription.id,
        delivery_id=str(delivery.id),
    )
