"""
Facade re-exports for the GitHub webhook handlers.

Core's unified GitHub webhook view dispatches to these: it verifies the signature on every
POST and routes pull-request events to the tasks handler.
"""

from products.tasks.backend.webhooks import (
    get_github_webhook_secret,
    handle_pull_request_event,
    verify_github_signature,
)

__all__ = [
    "get_github_webhook_secret",
    "handle_pull_request_event",
    "verify_github_signature",
]
