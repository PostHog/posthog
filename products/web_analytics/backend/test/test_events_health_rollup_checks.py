import datetime as dt

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.temporal.health_checks.rollups.checks import RollupHealthCheck
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, invalidate_published_days
from posthog.temporal.health_checks.rollups.tests.helpers import window_ending_yesterday

from products.event_definitions.backend.models import EventDefinition
from products.web_analytics.backend.models.health_rollups import EventsHealthDaily, SessionIdState
from products.web_analytics.backend.temporal.health_checks.no_live_events import NoLiveEventsCheck
from products.web_analytics.backend.temporal.health_checks.no_pageleave_events import NoPageleaveEventsCheck
from products.web_analytics.backend.temporal.health_checks.reverse_proxy import ReverseProxyCheck
from products.web_analytics.backend.temporal.health_checks.scroll_depth import ScrollDepthCheck
from products.web_analytics.backend.temporal.health_checks.web_vitals import WebVitalsCheck

Row = tuple[str, bool, bool, int]

PAGEVIEWS: Row = ("$pageview", False, False, 40)
PAGELEAVES: Row = ("$pageleave", False, False, 30)
PAGELEAVES_WITH_SCROLL: Row = ("$pageleave", False, True, 5)
WEB_VITALS: Row = ("$web_vitals", False, False, 10)
SCREENS: Row = ("$screen", False, False, 20)


@time_machine.travel("2026-10-29T12:00:00Z", tick=False)
class TestEventsHealthRollupChecks(ClickhouseTestMixin, BaseTest):
    def _insert(self, rows: list[Row], window: RollupWindow) -> None:
        EventsHealthDaily.objects.unscoped().bulk_create(
            EventsHealthDaily(
                team_id=self.team.id,
                day=window.start if index % 2 else window.end,
                event=event,
                has_custom_api_host=custom,
                has_scroll_depth=scroll,
                session_id_state=SessionIdState.VALID if event == "$pageview" else SessionIdState.NOT_APPLICABLE,
                event_count=count,
            )
            for index, (event, custom, scroll, count) in enumerate(rows)
        )

    def _publish_window_for_another_project(self, window: RollupWindow) -> None:
        other_team_id = self.team.id + 1000
        days = (window.start + dt.timedelta(days=offset) for offset in range((window.end - window.start).days + 1))
        EventsHealthDaily.objects.unscoped().bulk_create(
            EventsHealthDaily(
                team_id=other_team_id,
                day=day,
                event="$pageview",
                has_custom_api_host=False,
                has_scroll_depth=False,
                session_id_state=SessionIdState.VALID,
                event_count=1,
            )
            for day in days
        )
        invalidate_published_days(EventsHealthDaily)

    def _flagged(self, check: RollupHealthCheck, rows: list[Row]) -> bool:
        window = window_ending_yesterday(check.window_days)
        self._insert(rows, window)
        return self.team.id in check.detect_from_rollup([self.team.id], window)

    @parameterized.expand(
        [
            ("no_pageleave_pageviews_only", NoPageleaveEventsCheck(), [PAGEVIEWS], True),
            ("no_pageleave_with_pageleaves", NoPageleaveEventsCheck(), [PAGEVIEWS, PAGELEAVES], False),
            ("no_pageleave_without_pageviews", NoPageleaveEventsCheck(), [SCREENS], False),
            ("scroll_depth_never_sent", ScrollDepthCheck(), [PAGEVIEWS, PAGELEAVES], True),
            ("scroll_depth_sometimes_sent", ScrollDepthCheck(), [PAGELEAVES, PAGELEAVES_WITH_SCROLL], False),
            ("scroll_depth_without_pageleaves", ScrollDepthCheck(), [PAGEVIEWS], False),
            ("web_vitals_missing", WebVitalsCheck(), [PAGEVIEWS], True),
            ("web_vitals_present", WebVitalsCheck(), [PAGEVIEWS, WEB_VITALS], False),
            ("reverse_proxy_screens_count_toward_floor", ReverseProxyCheck(), [PAGEVIEWS, SCREENS], True),
            ("reverse_proxy_below_floor", ReverseProxyCheck(), [PAGEVIEWS], False),
            (
                "reverse_proxy_some_traffic_proxied",
                ReverseProxyCheck(),
                [PAGEVIEWS, SCREENS, ("$pageview", True, False, 1)],
                False,
            ),
            ("no_live_events_with_screens_only", NoLiveEventsCheck(), [SCREENS], False),
        ]
    )
    def test_rule(self, _name: str, check: RollupHealthCheck, rows: list[Row], expected: bool) -> None:
        self.assertEqual(self._flagged(check, rows), expected)

    @parameterized.expand([("silent", False, True), ("events_since_the_rollup_ended", True, False)])
    def test_no_live_events_probes_the_hours_after_the_rollup(
        self, _name: str, send_event_today: bool, expected: bool
    ) -> None:
        if send_event_today:
            _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp=dt.datetime.now(dt.UTC))
            flush_persons_and_events()

        self.assertEqual(self._flagged(NoLiveEventsCheck(), []), expected)

    @parameterized.expand(
        [
            ("web_project_gone_silent", True, "$pageview", True, True),
            ("app_project_gone_silent", True, "$screen", True, True),
            ("nothing_ingested_yet", False, None, False, True),
            ("server_only_project", True, "$mcp_tool_call", True, False),
            ("pageview_placeholder_never_seen", True, "$pageview", False, False),
        ]
    )
    def test_no_live_events_skips_projects_that_never_sent_web_events(
        self, _name: str, ingested_event: bool, defined_event: str | None, seen: bool, expected: bool
    ) -> None:
        self.team.ingested_event = ingested_event
        self.team.save()
        if defined_event:
            EventDefinition.objects.create(
                team=self.team,
                project_id=self.team.project_id,
                name=defined_event,
                last_seen_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=90) if seen else None,
            )
        self._publish_window_for_another_project(window_ending_yesterday(NoLiveEventsCheck.window_days))

        self.assertEqual(self.team.id in NoLiveEventsCheck().detect([self.team.id]), expected)
