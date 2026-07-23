"""Facade for slack_app.

The ONLY module other products are allowed to import. Keep the surface narrow:
every function here lives behind a tach contract check, so each addition has a
cost in cross-product coupling.

The facade currently serves two jobs: letting core's OAuth callback invalidate
the per-integration auth-state cache when a Slack install is reconnected, and
handing other products (tasks) a chat thread handler for posting task-lifecycle
updates back into the conversation that spawned a run. Everything is a stable
re-export so implementations can move around inside the product without
breaking callers.
"""

from __future__ import annotations

from products.slack_app.backend.providers import ChatThreadHandler, thread_handler_from_context
from products.slack_app.backend.services.slack_auth import invalidate_auth_state

__all__ = [
    "ChatThreadHandler",
    "invalidate_slack_integration_auth_state",
    "thread_handler_from_context",
]


def invalidate_slack_integration_auth_state(integration_id: int) -> None:
    """Drop the cached auth verdict for ``integration_id``.

    Call from core's OAuth completion path so a freshly-reconnected Slack
    install doesn't get pinned to the stale ``ok=false`` state we wrote when
    its previous token was revoked.
    """
    invalidate_auth_state(integration_id)
