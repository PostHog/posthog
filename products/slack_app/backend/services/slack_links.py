"""Links into Slack's own surfaces."""

from __future__ import annotations

from posthog.models.integration import Integration


def app_home_url(integration: Integration) -> str | None:
    """Deep link to this install's Home tab, where the model picker lives.

    The `app_redirect` form is https, so it survives as a link in any client and in a
    browser; `slack://app` only resolves natively. Both need the app id (`A…`), which the
    OAuth exchange already persisted on the integration — so this stays correct even
    where more than one Slack app is in play. A row installed by some other path may not
    carry it, which simply means no link.
    """
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"https://slack.com/app_redirect?app={app_id}&team={integration.integration_id}&tab=home"
