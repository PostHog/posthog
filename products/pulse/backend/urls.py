"""Relative deep links into the app for cited resources. One place so sources build them uniformly.

Relative (not absolute_uri) to match how brief evidence URLs are consumed in-app.
"""


def insight_url(team_id: int, short_id: str) -> str:
    return f"/project/{team_id}/insights/{short_id}"


def subscription_url(team_id: int, subscription_id: int) -> str:
    # The subscription page carries the full detail (backing resource + delivery status), so it's
    # the right landing spot for every subscription type — no need to branch on the resource.
    return f"/project/{team_id}/subscriptions/{subscription_id}"


def inbox_report_url(team_id: int, report_id: str) -> str:
    return f"/project/{team_id}/inbox/reports/{report_id}"
