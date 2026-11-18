"""Workflows' consumers: the customer-facing GitHub App endpoint, and the SES events SNS topic.

The registry imports this module on the first delivery, so it stays cheap: both handlers defer
their own product import.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _run_workflows(delivery: WebhookDelivery) -> None:
    from products.workflows.backend.facade.api import accept_github_event  # noqa: PLC0415

    accept_github_event(delivery)


def _run_workflows_ses_events(delivery: WebhookDelivery) -> None:
    from products.workflows.backend.facade.api import accept_ses_event  # noqa: PLC0415

    accept_ses_event(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="workflows",
        provider="github",
        app="posthog",
        event_types=frozenset({"issues", "issue_comment", "pull_request", "pull_request_review", "push"}),
        handler=_run_workflows,
    ),
    WebhookConsumer(
        name="workflows_ses_events",
        provider="sns",
        app="default",
        # Confirming the subscription is this consumer's business too: it means calling AWS back.
        event_types=frozenset({"SubscriptionConfirmation", "Notification"}),
        handler=_run_workflows_ses_events,
    ),
)
