from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _accept_pull_request_event(delivery: WebhookDelivery) -> None:
    from products.review_hog.backend.facade.github import (  # noqa: PLC0415 - keeps product models off the registry import path
        accept_pull_request_event,
    )

    accept_pull_request_event(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        # The name is the dedup cache key, so it keeps the name of its first job, automatic reviews.
        name="review_hog_authored_prs",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_accept_pull_request_event,
    ),
)
