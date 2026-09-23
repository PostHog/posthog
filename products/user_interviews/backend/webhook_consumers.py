"""User interviews' consumer on the Vapi endpoint."""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery
from posthog.ingress.vapi.provider import VAPI_EVENT_TYPES


def _queue_interview_storage(delivery: WebhookDelivery) -> None:
    from products.user_interviews.backend.facade.api import (  # noqa: PLC0415 - keeps the product's models and the Celery app off the registry's import path
        accept_vapi_event,
    )

    accept_vapi_event(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="user_interviews_vapi",
        provider="vapi",
        app="default",
        event_types=VAPI_EVENT_TYPES,
        handler=_queue_interview_storage,
    ),
)
