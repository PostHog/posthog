"""The inbound PandaDoc webhook for legal documents.

Ingress verifies the HMAC over the raw body and fans each batched event out to
`legal_documents_signatures` in `webhook_consumers.py`. A bad signature answers 404 rather
than 403, so an attacker cannot tell a wrong secret from an unknown route.

There is no per-IP throttle: PandaDoc delivers from a small shared pool of egress IPs, so
keying on them drops legitimate deliveries, and the HMAC check already proves provenance.
"""

from posthog.cloud_utils import is_cloud, is_dev_mode
from posthog.ingress.pandadoc.provider import build_pandadoc_provider
from posthog.ingress.views import build_webhook_view


def _pandadoc_integration_is_served() -> bool:
    # Self-hosted deployments do not run the PandaDoc integration, and the endpoint must never
    # leak that it exists. Dev mode keeps it on for local testing.
    return is_cloud() or is_dev_mode()


legal_document_pandadoc_webhook = build_webhook_view(build_pandadoc_provider(enabled=_pandadoc_integration_is_served))
