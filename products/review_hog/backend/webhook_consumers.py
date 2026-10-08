from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _enqueue_authored_review(delivery: WebhookDelivery) -> None:
    from products.review_hog.backend.facade.github import (  # noqa: PLC0415 - keeps product models off the registry import path
        enqueue_authored_pr_review,
    )

    enqueue_authored_pr_review(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="review_hog_authored_prs",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_enqueue_authored_review,
    ),
)
