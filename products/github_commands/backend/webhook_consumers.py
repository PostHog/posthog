"""GitHub commands' consumer on the customer-facing GitHub App endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers the
facade import, and the facade defers the task import until a comment holds a command.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _accept_comment(delivery: WebhookDelivery) -> None:
    from products.github_commands.backend.facade.api import accept_issue_comment  # noqa: PLC0415

    accept_issue_comment(delivery.payload)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="github_commands",
        provider="github",
        app="posthog",
        event_types=frozenset({"issue_comment"}),
        handler=_accept_comment,
    ),
)
