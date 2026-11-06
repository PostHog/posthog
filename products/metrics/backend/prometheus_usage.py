"""Report use of the Prometheus-compatible query API as a product analytics event.

A Grafana dashboard sends one request per panel on every refresh, so the event is sent at most one
time per window for each team, user, auth method and client. The event shows which teams query
their metrics from outside PostHog, not how many requests they send.
"""

from django.core.cache import cache

from posthog.event_usage import AnalyticsProps, report_user_action
from posthog.models import Team, User

# pinned: analytics event name and properties, renaming breaks the metrics usage dashboards
PROMETHEUS_API_USED_EVENT = "metrics prometheus api used"
USAGE_REPORT_WINDOW_SECONDS = 60 * 60


def report_prometheus_api_usage(
    *, team: Team, user: User, auth_method: str, client: str, analytics_props: AnalyticsProps
) -> None:
    window_key = f"metrics_prometheus_api_used:{team.pk}:{user.pk}:{auth_method}:{client}"
    if not cache.add(window_key, True, timeout=USAGE_REPORT_WINDOW_SECONDS):
        return
    report_user_action(
        user,
        PROMETHEUS_API_USED_EVENT,
        {"auth_method": auth_method, "client": client},
        team=team,
        analytics_props=analytics_props,
    )
