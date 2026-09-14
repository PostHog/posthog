"""Tasks' consumers on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: every handler defers
its own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_pr_backstop(delivery: WebhookDelivery) -> None:
    from products.tasks.backend.facade.webhooks import handle_pull_request_event  # noqa: PLC0415

    handle_pull_request_event(dict(delivery.payload))


def _run_pr_review(delivery: WebhookDelivery) -> None:
    from products.tasks.backend.facade.webhooks import handle_pull_request_review_event  # noqa: PLC0415

    handle_pull_request_review_event(dict(delivery.payload))


def _run_loops(delivery: WebhookDelivery) -> None:
    from products.tasks.backend.facade.webhooks import handle_github_event_for_loops  # noqa: PLC0415

    handle_github_event_for_loops(delivery.event_type, dict(delivery.payload), delivery.delivery_id or "")


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
    WebhookConsumer(
        name="loops",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment", "pull_request", "push"}),
        handler=_run_loops,
    ),
)
