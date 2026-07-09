"""Facade for slack_app.

The ONLY module other products are allowed to import. Keep the surface narrow:
every function here lives behind a tach contract check, so each addition has a
cost in cross-product coupling.

Today the facade exists for one job — letting core's OAuth callback invalidate
the per-integration auth-state cache when a Slack install is reconnected. We
expose the helper as a stable re-export so the implementation can move around
inside ``services/`` without breaking core.
"""

from __future__ import annotations

from products.slack_app.backend.services.slack_auth import invalidate_auth_state


def invalidate_slack_integration_auth_state(integration_id: int) -> None:
    """Drop the cached auth verdict for ``integration_id``.

    Call from core's OAuth completion path so a freshly-reconnected Slack
    install doesn't get pinned to the stale ``ok=false`` state we wrote when
    its previous token was revoked.
    """
    invalidate_auth_state(integration_id)
