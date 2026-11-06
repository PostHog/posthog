from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery


def _enqueue_external_references(delivery: WebhookDelivery) -> None:
    from products.error_tracking.backend.facade.github import (  # noqa: PLC0415 - keeps Celery and product logic off the registry import path
        enqueue_github_external_references,
    )

    enqueue_github_external_references(delivery.event_type, dict(delivery.payload))


def _enqueue_linear_status_sync(delivery: WebhookDelivery) -> None:
    from products.error_tracking.backend.facade.linear import (  # noqa: PLC0415 - keeps Celery and product logic off the registry import path
        enqueue_linear_status_sync,
    )

    enqueue_linear_status_sync(dict(delivery.payload))


def _linear_status_sync_ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
    from products.error_tracking.backend.facade.issues import (  # noqa: PLC0415 - keeps product logic off the registry import path
        linear_delivery_ownership,
    )

    return linear_delivery_ownership(dict(delivery.payload))


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="error_tracking_external_references",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "pull_request"}),
        handler=_enqueue_external_references,
    ),
    WebhookConsumer(
        name="error_tracking_linear_status_sync",
        provider="linear",
        app="posthog",
        event_types=frozenset({"Issue"}),
        handler=_enqueue_linear_status_sync,
        ownership=_linear_status_sync_ownership,
    ),
)
