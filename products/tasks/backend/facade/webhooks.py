"""
Facade re-exports for the GitHub and Linear webhook handlers.

Core's unified GitHub webhook view dispatches to these: it verifies the signature on every
POST and routes pull-request events to the tasks handler. Core's ``/webhooks/linear`` route
delegates whole requests to ``handle_linear_agent_webhook`` (verification included).
"""

from products.tasks.backend.logic.linear_agent.webhooks import handle_linear_agent_webhook
from products.tasks.backend.webhooks import (
    get_github_webhook_secret,
    handle_pull_request_event,
    verify_github_signature,
)

__all__ = [
    "get_github_webhook_secret",
    "handle_linear_agent_webhook",
    "handle_pull_request_event",
    "verify_github_signature",
]
