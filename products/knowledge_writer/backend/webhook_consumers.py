from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _record_pull_request_event(delivery: WebhookDelivery) -> None:
    from products.knowledge_writer.backend.facade.api import (  # noqa: PLC0415 - keeps product models off the registry import path
        record_pull_request_event,
    )

    record_pull_request_event(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="knowledge_writer_merged_pull_requests",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_record_pull_request_event,
    ),
)
