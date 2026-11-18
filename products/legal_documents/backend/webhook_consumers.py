"""Legal documents' consumer on the PandaDoc endpoint.

The registry imports this module on the first delivery, so it stays cheap: the handler defers
the facade import, which drags the models and the PandaDoc client in.
"""

from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery
from posthog.ingress.pandadoc.provider import PANDADOC_EVENT_TYPES


def _run_legal_documents(delivery: WebhookDelivery) -> None:
    from products.legal_documents.backend.facade.api import accept_pandadoc_event  # noqa: PLC0415

    accept_pandadoc_event(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="legal_documents_signatures",
        provider="pandadoc",
        app="default",
        event_types=PANDADOC_EVENT_TYPES,
        handler=_run_legal_documents,
    ),
)
