from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery

from products.docs_freshness.backend.facade.api import accept_pull_request_event, accept_push_event


def _accept_pull_request_event(delivery: WebhookDelivery) -> None:
    accept_pull_request_event(delivery.payload)


def _accept_push_event(delivery: WebhookDelivery) -> None:
    accept_push_event(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="docs_freshness_pull_request_heads",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_accept_pull_request_event,
    ),
    WebhookConsumer(
        name="docs_freshness_landed_commits",
        provider="github",
        app="posthog",
        event_types=frozenset({"push"}),
        handler=_accept_push_event,
    ),
)
