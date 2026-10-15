from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _enqueue_external_references(delivery: WebhookDelivery) -> None:
    from products.error_tracking.backend.facade.github import (  # noqa: PLC0415 - keeps Celery and product logic off the registry import path
        enqueue_github_external_references,
    )

    enqueue_github_external_references(delivery.event_type, dict(delivery.payload))


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="error_tracking_external_references",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "pull_request"}),
        handler=_enqueue_external_references,
    ),
)
