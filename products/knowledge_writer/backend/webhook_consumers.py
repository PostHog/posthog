from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _record_merged_pull_request(delivery: WebhookDelivery) -> None:
    from products.knowledge_writer.backend.facade.api import (  # noqa: PLC0415 - keeps product models off the registry import path
        record_merged_pull_request,
    )

    record_merged_pull_request(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="knowledge_writer_merged_pull_requests",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_record_merged_pull_request,
    ),
)
