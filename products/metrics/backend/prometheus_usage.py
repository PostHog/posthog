"""Report use of the Prometheus-compatible query API as a product analytics event.

A Grafana dashboard sends one request per panel on every refresh, so the event is sent at most one
time per window for each team, user, auth method and client. The event shows which teams query
their metrics from outside PostHog, not how many requests they send.
"""

from django.core.cache import cache

from rest_framework.request import Request

from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.event_usage import report_user_action
from posthog.models import Team

# pinned: analytics event name and properties, renaming breaks the metrics usage dashboards
PROMETHEUS_API_USED_EVENT = "metrics prometheus api used"
USAGE_REPORT_WINDOW_SECONDS = 60 * 60


def _auth_method(request: Request) -> str:
    authenticator = request.successful_authenticator
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return "personal_api_key"
    if isinstance(authenticator, SessionAuthentication):
        return "session"
    return "other"


def _client(request: Request) -> str:
    # Grafana sends `Grafana/<version>` as the user agent of data source requests.
    return "grafana" if request.headers.get("User-Agent", "").startswith("Grafana/") else "other"


def report_prometheus_api_usage(request: Request, team: Team) -> None:
    auth_method = _auth_method(request)
    client = _client(request)
    window_key = f"metrics_prometheus_api_used:{team.pk}:{request.user.pk}:{auth_method}:{client}"
    if not cache.add(window_key, True, timeout=USAGE_REPORT_WINDOW_SECONDS):
        return
    report_user_action(
        request.user,
        PROMETHEUS_API_USED_EVENT,
        {"auth_method": auth_method, "client": client},
        team=team,
        request=request,
    )
