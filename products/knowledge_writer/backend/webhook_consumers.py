from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _record_default_branch_push(delivery: WebhookDelivery) -> None:
    from products.knowledge_writer.backend.facade.api import (  # noqa: PLC0415 - keeps product models off the registry import path
        record_default_branch_push,
    )

    record_default_branch_push(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="knowledge_writer_default_branch_pushes",
        provider="github",
        app="posthog",
        event_types=frozenset({"push"}),
        handler=_record_default_branch_push,
    ),
)
