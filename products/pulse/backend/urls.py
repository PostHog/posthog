"""Relative deep links into the app for cited resources. One place so sources build them uniformly.

Relative (not absolute_uri) to match how brief evidence URLs are consumed in-app.
"""


def insight_url(team_id: int, short_id: str) -> str:
    return f"/project/{team_id}/insights/{short_id}"


def dashboard_url(team_id: int, dashboard_id: int) -> str:
    return f"/project/{team_id}/dashboard/{dashboard_id}"


def subscription_url(
    team_id: int, subscription_id: int, *, insight_short_id: str | None = None, dashboard_id: int | None = None
) -> str:
    """Deep link to a subscription. Mirrors Subscription.url's routing: an insight- or dashboard-backed
    subscription links to its resource; a prompt (or otherwise relationless) one links to the project's
    subscriptions list — so every subscription type gets a navigable link, never an empty one."""
    if insight_short_id:
        return insight_url(team_id, insight_short_id)
    if dashboard_id:
        return dashboard_url(team_id, dashboard_id)
    return f"/project/{team_id}/subscriptions/{subscription_id}"
