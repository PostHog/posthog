"""The inbound webhook view for the dedicated Stamphog GitHub App.

This is a standalone endpoint for Stamphog's own GitHub App. It does not share the
customer-facing App's endpoint. The integration layer wires the URL at this name.
"""

from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.views import build_webhook_view

# Built once per process: the provider only stores the secret getter, it never reads the secret here.
stamphog_github_webhook = build_webhook_view(build_github_provider("stamphog"))

__all__ = ["stamphog_github_webhook"]
