import datetime as dt

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.processing import _process_batch_detection
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

    def _define_events(self, events: list[tuple[str, int | None]]) -> None:
        self.team.ingested_event = True
        self.team.save()
        for event, last_seen_days_ago in events:
            EventDefinition.objects.create(
                team=self.team,
                project_id=self.team.project_id,
                name=event,
                last_seen_at=None
                if last_seen_days_ago is None
                else dt.datetime.now(dt.UTC) - dt.timedelta(days=last_seen_days_ago),
            )

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
            ("reverse_proxy_app_only_project", ReverseProxyCheck(), [("$screen", False, False, 500)], False),
            ("reverse_proxy_below_floor", ReverseProxyCheck(), [PAGEVIEWS], False),
            (
                "reverse_proxy_proxied_screens_do_not_clear_unproxied_web",
                ReverseProxyCheck(),
                [PAGEVIEWS, PAGEVIEWS, ("$screen", True, False, 1)],
                True,
            ),
            (
                "reverse_proxy_some_traffic_proxied",
                ReverseProxyCheck(),
                [PAGEVIEWS, PAGEVIEWS, ("$pageview", True, False, 1)],
                False,
            ),
        ]
    )
    def test_rule(self, _name: str, check: RollupHealthCheck, rows: list[Row], expected: bool) -> None:
        self.assertEqual(self._flagged(check, rows), expected)

    @parameterized.expand([("silent", False, True), ("events_since_the_rollup_ended", True, False)])
    def test_no_live_events_probes_the_hours_after_the_rollup(
        self, _name: str, send_event_today: bool, expected: bool
    ) -> None:
        self._define_events([("$pageview", 40)])
        if send_event_today:
            _create_event(team=self.team, event="$pageview", distinct_id="user", timestamp=dt.datetime.now(dt.UTC))
            flush_persons_and_events()

        self.assertEqual(self._flagged(NoLiveEventsCheck(), []), expected)

    @parameterized.expand(
        [
            ("web_project_gone_silent", True, [("$pageview", 40)], [], HealthIssue.Severity.CRITICAL, ["$pageview"]),
            ("app_project_gone_silent", True, [("$screen", 40)], [], HealthIssue.Severity.CRITICAL, ["$screen"]),
            (
                "web_project_dark_past_horizon",
                True,
                [("$pageview", 120)],
                [],
                HealthIssue.Severity.CRITICAL,
                ["$pageview"],
            ),
            ("nothing_ingested_yet", False, [], [], HealthIssue.Severity.CRITICAL, ["$pageview", "$screen"]),
            ("server_only_project", True, [("$mcp_tool_call", 40)], [], None, None),
            ("pageview_placeholder_never_seen", True, [("$pageview", None)], [], None, None),
            ("app_project_sending_screens", True, [("$screen", 1)], [SCREENS], None, None),
            (
                "mixed_project_sending_both",
                True,
                [("$pageview", 1), ("$screen", 1)],
                [PAGEVIEWS, SCREENS],
                None,
                None,
            ),
            (
                "mixed_project_web_gone_silent",
                True,
                [("$pageview", 40), ("$screen", 1)],
                [SCREENS],
                HealthIssue.Severity.WARNING,
                ["$pageview"],
            ),
            ("mixed_project_web_past_horizon", True, [("$pageview", 120), ("$screen", 1)], [SCREENS], None, None),
        ]
    )
    def test_no_live_events_judges_each_event_type_the_project_sends(
        self,
        _name: str,
        ingested_event: bool,
        defined_events: list[tuple[str, int | None]],
        rows: list[Row],
        expected_severity: str | None,
        expected_events: list[str] | None,
    ) -> None:
        if ingested_event:
            self._define_events(defined_events)
        window = window_ending_yesterday(NoLiveEventsCheck.window_days)
        self._insert(rows, window)
        self._publish_window_for_another_project(window)

        results = NoLiveEventsCheck().detect([self.team.id]).get(self.team.id)

        if expected_severity is None:
            self.assertIsNone(results)
        else:
            assert results is not None
            self.assertEqual(
                [(result.severity, result.payload["events"]) for result in results],
                [(expected_severity, expected_events)],
            )

    def test_no_live_events_alerts_again_when_the_last_platform_stops(self) -> None:
        self._define_events([("$pageview", 40), ("$screen", 1)])
        window = window_ending_yesterday(NoLiveEventsCheck.window_days)
        self._insert([SCREENS], window)
        self._publish_window_for_another_project(window)
        check = NoLiveEventsCheck()

        _process_batch_detection([self.team.id], check.kind, check.detect)
        EventsHealthDaily.objects.unscoped().filter(team_id=self.team.id).delete()
        invalidate_published_days(EventsHealthDaily)
        escalation = _process_batch_detection([self.team.id], check.kind, check.detect)

        self.assertEqual(escalation.issues_upserted, 1)
        self.assertCountEqual(
            HealthIssue.objects.filter(team_id=self.team.id, kind=check.kind).values_list("severity", "status"),
            [
                (HealthIssue.Severity.WARNING, HealthIssue.Status.RESOLVED),
                (HealthIssue.Severity.CRITICAL, HealthIssue.Status.ACTIVE),
            ],
        )
