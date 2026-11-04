from collections import defaultdict

from django.db.models import Q, Sum

from posthog.constants import (
    PAGEVIEW_EVENT as PAGEVIEW,
    SCREEN_EVENT as SCREEN,
)
from posthog.dataclasses import frozen
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, window_rows

from products.web_analytics.backend.models.health_rollups import EventsHealthDaily, HostProxyDaily, SessionIdState

PAGELEAVE = "$pageleave"
WEB_VITALS = "$web_vitals"


@frozen
class EventsHealthTotals:
    pageviews: int = 0
    screens: int = 0
    pageleaves: int = 0
    pageleaves_with_scroll_depth: int = 0
    web_vitals: int = 0
    proxied_browser_events: int = 0
    pageviews_unusable_session_id: int = 0
    pageviews_absent_session_id: int = 0

    @property
    def browser_events(self) -> int:
        return self.pageviews + self.screens


_EMPTY_TOTALS = EventsHealthTotals()


def events_health_totals(team_ids: list[int], window: RollupWindow) -> dict[int, EventsHealthTotals]:
    """Summed web event counts per team over the window. A team with no rows maps to all zeros."""

    def total(condition: Q) -> Sum:
        return Sum("event_count", filter=condition, default=0)

    rows = (
        window_rows(EventsHealthDaily, team_ids, window)
        .values("team_id")
        .annotate(
            pageviews=total(Q(event=PAGEVIEW)),
            screens=total(Q(event=SCREEN)),
            pageleaves=total(Q(event=PAGELEAVE)),
            pageleaves_with_scroll_depth=total(Q(event=PAGELEAVE, has_scroll_depth=True)),
            web_vitals=total(Q(event=WEB_VITALS)),
            proxied_browser_events=total(Q(event__in=[PAGEVIEW, SCREEN], has_custom_api_host=True)),
            pageviews_unusable_session_id=total(
                Q(
                    event=PAGEVIEW,
                    session_id_state__in=[SessionIdState.NOT_UUIDV7, SessionIdState.ABSENT_OR_NOT_UUID],
                )
            ),
            pageviews_absent_session_id=total(Q(event=PAGEVIEW, session_id_state=SessionIdState.ABSENT_OR_NOT_UUID)),
        )
    )
    totals = {
        row["team_id"]: EventsHealthTotals(
            pageviews=row["pageviews"],
            screens=row["screens"],
            pageleaves=row["pageleaves"],
            pageleaves_with_scroll_depth=row["pageleaves_with_scroll_depth"],
            web_vitals=row["web_vitals"],
            proxied_browser_events=row["proxied_browser_events"],
            pageviews_unusable_session_id=row["pageviews_unusable_session_id"],
            pageviews_absent_session_id=row["pageviews_absent_session_id"],
        )
        for row in rows
    }
    return {team_id: totals.get(team_id, _EMPTY_TOTALS) for team_id in team_ids}


@frozen
class HostTraffic:
    host: str
    event_count: int
    proxied: bool


def host_traffic(team_ids: list[int], window: RollupWindow, *, min_events: int) -> dict[int, list[HostTraffic]]:
    """Hosts per team with at least `min_events` events over the window. A host is proxied when any of its events was."""
    rows = (
        window_rows(HostProxyDaily, team_ids, window)
        .values("team_id", "host")
        .annotate(
            total_events=Sum("event_count"),
            proxied_events=Sum("event_count", filter=Q(has_custom_api_host=True), default=0),
        )
        .filter(total_events__gte=min_events)
    )
    traffic: defaultdict[int, list[HostTraffic]] = defaultdict(list)
    for row in rows:
        traffic[row["team_id"]].append(
            HostTraffic(host=row["host"], event_count=row["total_events"], proxied=row["proxied_events"] > 0)
        )
    return dict(traffic)
