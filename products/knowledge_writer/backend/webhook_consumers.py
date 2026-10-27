from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

MERGE_REPOSITORY = "posthog/posthog"
MERGE_REF = "refs/heads/master"


def _start_backstop_for_merge(delivery: WebhookDelivery) -> None:
    payload = delivery.payload
    if payload.get("ref") != MERGE_REF:
        return
    if str((payload.get("repository") or {}).get("full_name", "")).lower() != MERGE_REPOSITORY:
        return
    from products.knowledge_writer.backend.facade.api import record_merge_push  # noqa: PLC0415

    record_merge_push(str(payload.get("after", "")))


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="knowledge_writer_merge_backstop",
        provider="github",
        app="posthog",
        event_types=frozenset({"push"}),
        handler=_start_backstop_for_merge,
    ),
)
