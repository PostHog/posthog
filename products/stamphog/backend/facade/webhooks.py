"""Facade re-export for the dedicated Stamphog GitHub App webhook view.

Core routes a standalone URL at this view; it stays out of the unified
``posthog.urls.github_webhook`` fan-out because Stamphog is its own GitHub App.
"""

from products.stamphog.backend.presentation.webhooks import stamphog_github_webhook

__all__ = ["stamphog_github_webhook"]
