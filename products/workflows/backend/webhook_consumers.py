"""Workflows' consumer on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
its own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_workflows(delivery: WebhookDelivery) -> None:
    from products.workflows.backend.facade.api import accept_github_event  # noqa: PLC0415

    accept_github_event(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="workflows",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment", "pull_request", "pull_request_review", "push"}),
        handler=_run_workflows,
    ),
)
