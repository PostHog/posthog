# Re-export from the canonical location for backward compatibility
from django.conf import settings

from products.signals.backend.signal_metadata import EMBEDDING_MODEL
from products.signals.backend.temporal.signal_queries import _ensure_tz_aware, soft_delete_report_signals

__all__ = [
    "EMBEDDING_MODEL",
    "_ensure_tz_aware",
    "report_inbox_url",
    "soft_delete_report_signals",
]


def report_inbox_url(team_id: int, report_id: str) -> str:
    """Canonical deep link to a report in the PostHog inbox. The one URL shape every surface that
    links a report (Slack notifications, scout delivery, the report serializer) should build from."""
    return f"{settings.SITE_URL.rstrip('/')}/project/{team_id}/inbox/reports/{report_id}"
