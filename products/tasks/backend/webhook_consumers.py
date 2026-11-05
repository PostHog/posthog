"""Tasks' consumers on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: every handler defers
its own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_pr_backstop(delivery: WebhookDelivery) -> None:
    from products.tasks.backend.facade.api import accept_github_pull_request  # noqa: PLC0415

    accept_github_pull_request(delivery)


def _run_pr_review(delivery: WebhookDelivery) -> None:
    from products.tasks.backend.facade.api import accept_github_pull_request_review  # noqa: PLC0415

    accept_github_pull_request_review(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="tasks_pr_backstop",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_run_pr_backstop,
    ),
    WebhookConsumer(
        name="tasks_pr_review",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request_review"}),
        handler=_run_pr_review,
    ),
)
