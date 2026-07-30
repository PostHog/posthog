from django.conf import settings


def report_inbox_url(team_id: int, report_id: str) -> str:
    """Canonical deep link to a report in the PostHog inbox. The one URL shape every surface that
    links a report (Slack notifications, scout delivery, the report serializer) should build from."""
    return f"{settings.SITE_URL.rstrip('/')}/project/{team_id}/inbox/reports/{report_id}"
