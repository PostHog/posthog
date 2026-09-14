import datetime as dt
from collections import Counter, defaultdict

from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models import Team

from products.marketing_analytics.backend.demo.events import MarketingEventGenerator
from products.marketing_analytics.backend.demo.world import EVENT_PAGEVIEW


class TestMarketingDemoTraffic(SimpleTestCase):
    def test_traffic_has_returning_visitors_and_multi_page_sessions(self) -> None:
        now = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
        with patch("products.marketing_analytics.backend.demo.events.create_event") as capture:
            MarketingEventGenerator(Team(), seed="traffic-mix", days_past=14, scale=0.02, now=now).generate()

        pageviews = [call.kwargs for call in capture.call_args_list if call.kwargs["event"] == EVENT_PAGEVIEW]
        visitors = {event["distinct_id"] for event in pageviews}
        sessions = Counter(event["properties"]["$session_id"] for event in pageviews)
        visitor_days: dict[str, set[dt.date]] = defaultdict(set)
        for event in pageviews:
            visitor_days[event["distinct_id"]].add(event["timestamp"].date())

        assert len(visitors) < len(sessions) < len(pageviews)
        assert any(len(days) > 1 for days in visitor_days.values())
        assert any(count == 1 for count in sessions.values())
        assert any(count > 1 for count in sessions.values())
        assert all(event["timestamp"] < now for event in pageviews)

        for start, end in [
            (now - dt.timedelta(days=14), now - dt.timedelta(days=7)),
            (now - dt.timedelta(days=7), now),
        ]:
            period = [event for event in pageviews if start <= event["timestamp"] < end]
            assert (
                len({event["distinct_id"] for event in period})
                < len({event["properties"]["$session_id"] for event in period})
                < len(period)
            )

        timestamps: dict[str, list[dt.datetime]] = defaultdict(list)
        for event in pageviews:
            timestamps[event["properties"]["$session_id"]].append(event["timestamp"])
        assert any(max(times) > min(times) for times in timestamps.values())
