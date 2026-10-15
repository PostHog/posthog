from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError
from posthog.models import PropertyDefinition

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.facade.contracts import InsightDataChecks, InsightDataChecksCoverage
from products.product_analytics.backend.facade.data_checks import run_insight_data_checks
from products.product_analytics.backend.facade.enums import InsightDataCheckKey, InsightDataCheckLevel
from products.product_analytics.backend.insight_data_check_days import newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    CheckedEvents,
    SampledEvents,
    evaluate_data_checks,
)

PASSED = InsightDataCheckLevel.PASSED
WARNING = InsightDataCheckLevel.WARNING
PROBLEM = InsightDataCheckLevel.PROBLEM
SKIPPED = InsightDataCheckLevel.SKIPPED
LOCAL = InsightDataCheckKey.LOCAL_DEVELOPMENT
BOTS = InsightDataCheckKey.BOT_TRAFFIC
DUPLICATES = InsightDataCheckKey.DUPLICATE_EVENTS
NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
EVENT = "signed up"
WIDELY_SENT_EVENT = "opened app"
SENT_ON_THE_FREE_PLAN = "invited teammate"
BOT_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"
CRAWLER_IP = "66.249.84.5"
LOCAL_HOST = "localhost:8010"
CHECKS_MODULE = "products.product_analytics.backend.insight_data_checks"
RESULTS_MODULE = "products.product_analytics.backend.insight_data_check_results"
ON_LOCAL_HOST = {"key": "$host", "value": [LOCAL_HOST], "operator": "exact", "type": "event"}
FROM_A_BOT = {"key": "$raw_user_agent", "value": [BOT_USER_AGENT], "operator": "exact", "type": "event"}
IS_PAID = {"key": "plan", "value": ["paid"], "operator": "exact", "type": "event"}
HAS_NO_PLAN_TODAY = {"key": "plan", "value": "is_not_set", "operator": "is_not_set", "type": "person"}
ONE_STEP = [{"kind": "EventsNode", "event": EVENT}]
TWO_STEPS = [{"kind": "EventsNode", "event": EVENT}, {"kind": "EventsNode", "event": EVENT}]
SEVEN_DAYS = [date(2026, 3, 1) + timedelta(days=offset) for offset in range(7)]


def checked(
    sampled_events: int,
    *,
    local: int | None = 0,
    bots: int = 0,
    repeats: int = 0,
    sample_rate: float = 1.0,
    newest_days_of_a_longer_range: int | None = None,
) -> CheckedEvents:
    return CheckedEvents(
        local_events=local,
        sample=SampledEvents(
            rate=sample_rate,
            events=sampled_events,
            bot_events=bots,
            repeated_events=repeats,
            distinct_ids=sampled_events,
        ),
        days_checked=newest_days_of_a_longer_range or 1,
        checked_whole_range=newest_days_of_a_longer_range is None,
    )


class TestEvaluateDataChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("local_tiny_share_still_counts", checked(1_000_000, local=60), {LOCAL: WARNING}),
            ("local_under_50_events", checked(100, local=49), {}),
            ("local_fifth_is_a_problem", checked(1000, local=200), {LOCAL: PROBLEM}),
            ("local_too_many_events_to_count", checked(1000, local=None), {LOCAL: SKIPPED}),
            ("bots_small_share_is_a_warning", checked(10_000, bots=200), {BOTS: WARNING}),
            (
                "bots_under_50_sampled_events_but_over_50_in_the_range",
                checked(1000, bots=40, sample_rate=0.1),
                {BOTS: WARNING},
            ),
            ("bots_under_one_percent", checked(100_000, bots=500), {}),
            ("duplicates_under_100_events", checked(1000, repeats=99), {}),
            ("duplicates_under_five_percent", checked(10_000, repeats=400), {}),
            ("duplicates_over_both_floors", checked(10_000, repeats=600), {DUPLICATES: WARNING}),
            (
                "duplicates_under_100_sampled_events_but_over_100_in_the_range",
                checked(1000, repeats=80, sample_rate=0.01),
                {DUPLICATES: WARNING},
            ),
            ("duplicates_fifth_is_a_problem", checked(1000, repeats=250), {DUPLICATES: PROBLEM}),
            ("sample_too_small_to_check", checked(500, sample_rate=0.1), {BOTS: SKIPPED, DUPLICATES: SKIPPED}),
        ]
    )
    def test_level_follows_count_and_share(
        self,
        _name: str,
        checked_events: CheckedEvents,
        expected: dict[InsightDataCheckKey, InsightDataCheckLevel],
    ) -> None:
        checks = evaluate_data_checks(checked_events)
        assert {check.key: check.level for check in checks} == {
            **dict.fromkeys(InsightDataCheckKey, PASSED),
            **expected,
        }

    @parameterized.expand(
        [
            (
                "count_over_the_whole_range",
                LOCAL,
                checked(1_000_000, local=66),
                "66 of these events came from local development",
            ),
            (
                "count_on_the_newest_days_of_a_longer_range",
                LOCAL,
                checked(1_000_000, local=66, newest_days_of_a_longer_range=7),
                "In the last 7 days, 66 of these events came from local development",
            ),
            ("pass_on_every_event", BOTS, checked(50_000), "No bots or crawlers found"),
            (
                "pass_on_a_sample",
                BOTS,
                checked(50_000, sample_rate=0.5),
                "No bots or crawlers found in a sample of 50,000 events",
            ),
            (
                "estimate_from_a_sample",
                BOTS,
                checked(50_000, bots=5000, sample_rate=0.5),
                "About 10% of these events came from bots and crawlers",
            ),
        ]
    )
    def test_result_says_what_its_number_covers(
        self, _name: str, key: InsightDataCheckKey, checked_events: CheckedEvents, expected: str
    ) -> None:
        results = {check.key: check.result for check in evaluate_data_checks(checked_events)}
        assert results[key] == expected


class TestNewestDaysWithin(SimpleTestCase):
    @parameterized.expand(
        [
            ("days_within_the_budget", 1000, SEVEN_DAYS),
            ("budget_reached", 30, SEVEN_DAYS[-3:]),
            ("newest_day_alone_over_the_budget", 5, SEVEN_DAYS[-1:]),
        ]
    )
    def test_keeps_the_newest_days_within_the_budget(self, _name: str, budget: int, expected: list[date]) -> None:
        assert newest_days_within(dict.fromkeys(SEVEN_DAYS, 10), budget) == expected


@time_machine.travel(NOW, tick=False)
@patch(f"{CHECKS_MODULE}.SIZING_SAMPLE_ONE_IN", 1)
@patch(f"{CHECKS_MODULE}.MAX_CHECKED_DAYS", 10_000)
class TestInsightDataChecks(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.test_account_filters = [
            {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()
        _create_person(team=self.team, distinct_ids=["real"], properties={"email": "real@example.com"})
        _create_person(team=self.team, distinct_ids=["internal"], properties={"email": "dev@posthog.com"})
        self._second = 0
        self._events(200)
        self._events(60, distinct_id="internal")
        self._events(60, properties={"$host": LOCAL_HOST})
        self._events(30, properties={"$raw_user_agent": BOT_USER_AGENT, "$group_0": "acme"})
        self._events(30, properties={"$raw_user_agent": BROWSER_USER_AGENT, "$ip": CRAWLER_IP, "$group_0": "acme"})
        self._events(30, properties={"$host": LOCAL_HOST, "$process_person_profile": False})
        for _ in range(110):
            self._events(2, seconds_apart=0, properties={"$current_url": "https://example.com/pricing"})
        self._events(50, event="another event", properties={"$host": LOCAL_HOST})
        self._events(50, days_ago=70, properties={"$host": LOCAL_HOST})
        self._events(40, event=SENT_ON_THE_FREE_PLAN, person_properties={"plan": "free"})
        flush_persons_and_events()

    def _events(
        self,
        count: int,
        *,
        distinct_id: str = "real",
        event: str = EVENT,
        days_ago: int = 1,
        seconds_apart: int = 1,
        properties: Mapping[str, Any] = MappingProxyType({}),
        person_properties: Mapping[str, Any] = MappingProxyType({}),
    ) -> None:
        for _ in range(count):
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=NOW - timedelta(days=days_ago, seconds=self._second),
                properties=dict(properties),
                person_properties=dict(person_properties),
            )
            self._second += seconds_apart
        self._second += 1

    def _query(self, series: list[dict[str, Any]] = ONE_STEP, **source: Any) -> dict[str, Any]:
        return {
            "kind": "InsightVizNode",
            "source": {
                # Not a trends query: the repo's crossing scan reads one in a test as a run of web analytics code.
                "kind": "LifecycleQuery",
                "series": series,
                "dateRange": {"date_from": "-60d"},
                **source,
            },
        }

    def _check(self, query: dict[str, Any]) -> InsightDataChecks:
        return run_insight_data_checks(query, team=self.team, user=self.user)

    def _coverage(self, result: InsightDataChecks) -> InsightDataChecksCoverage:
        assert result.coverage is not None
        return result.coverage

    def _events_checked(self, query: dict[str, Any]) -> int | None:
        return self._coverage(self._check(query)).events_checked

    def test_counts_each_problem_in_the_events_the_insight_reads(self) -> None:
        result = self._check(self._query())

        coverage = self._coverage(result)
        assert result.status == "warning"
        assert coverage.events_checked == 600
        assert coverage.days_checked == coverage.days_in_range
        assert {check.key: (check.level, check.events) for check in result.checks} == {
            "local_development": ("warning", 60),
            "bot_traffic": ("warning", 60),
            "duplicate_events": ("warning", 110),
        }

    @parameterized.expand(
        [
            ("internal_users_filter", {"filterTestAccounts": True}, 540),
            ("property_filter", {"properties": [ON_LOCAL_HOST]}, 60),
            (
                "filter_on_the_series",
                {"series": [{"kind": "EventsNode", "event": EVENT, "properties": [ON_LOCAL_HOST]}]},
                60,
            ),
            (
                "a_filter_on_each_series",
                {
                    "kind": "StickinessQuery",
                    "series": [
                        {"kind": "EventsNode", "event": EVENT, "properties": [ON_LOCAL_HOST]},
                        {"kind": "EventsNode", "properties": [FROM_A_BOT]},
                    ],
                },
                120,
            ),
            (
                "series_that_counts_groups",
                {
                    "kind": "StickinessQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": EVENT,
                            "math": "unique_group",
                            "math_group_type_index": 0,
                        }
                    ],
                },
                60,
            ),
            ("insight_that_counts_groups", {"aggregation_group_type_index": 0}, 60),
            (
                "funnel_that_counts_a_property",
                {
                    "kind": "FunnelsQuery",
                    "series": TWO_STEPS,
                    "funnelsFilter": {"funnelAggregateByHogQL": "properties.$current_url"},
                },
                220,
            ),
            ("shorter_date_range", {"kind": "StickinessQuery", "dateRange": {"date_from": "-12h"}}, 0),
            ("date_range_without_a_start", {"dateRange": {}}, 600),
            ("weekdays", {"kind": "StickinessQuery", "dateRange": {"date_from": "-80d", "daysOfWeek": [2]}}, 50),
            (
                "query_modifiers",
                {
                    "series": [{"kind": "EventsNode", "event": SENT_ON_THE_FREE_PLAN}],
                    "properties": [HAS_NO_PLAN_TODAY],
                    "modifiers": {"personsOnEventsMode": "person_id_override_properties_joined"},
                },
                40,
            ),
        ]
    )
    def test_checks_only_what_the_insights_own_filters_keep(
        self, _name: str, source: dict[str, Any], events_checked: int
    ) -> None:
        assert self._events_checked(self._query(**source)) == events_checked

    @parameterized.expand(
        [
            ("trends_reads_the_cohort", "TrendsQuery", ONE_STEP, ["@posthog.com"], [], 60),
            (
                "trends_reads_everyone_when_all_users_is_a_value",
                "TrendsQuery",
                ONE_STEP,
                ["@posthog.com"],
                ["all"],
                630,
            ),
            (
                "funnel_with_two_cohorts_reads_them",
                "FunnelsQuery",
                TWO_STEPS,
                ["@posthog.com", "@nobody.example"],
                [],
                60,
            ),
            ("funnel_with_one_cohort_reads_everyone", "FunnelsQuery", TWO_STEPS, ["@posthog.com"], [], 630),
        ]
    )
    def test_checks_the_people_a_cohort_breakdown_reads(
        self,
        _name: str,
        kind: str,
        series: list[dict[str, Any]],
        cohort_domains: list[str],
        other_values: list[str],
        events_checked: int,
    ) -> None:
        cohorts = [
            Cohort.objects.create(
                team=self.team,
                name=domain,
                groups=[{"properties": [{"key": "email", "value": domain, "operator": "icontains", "type": "person"}]}],
            )
            for domain in cohort_domains
        ]
        for cohort in cohorts:
            cohort.calculate_people_ch(pending_version=0)
        query = self._query(
            series,
            kind=kind,
            breakdownFilter={
                "breakdown_type": "cohort",
                "breakdown": [*(cohort.id for cohort in cohorts), *other_values],
            },
        )

        assert self._events_checked(query) == events_checked

    def test_a_first_time_series_checks_only_the_events_in_its_date_range(self) -> None:
        query = self._query([{"kind": "EventsNode", "event": EVENT, "math": "first_time_for_user"}], kind="TrendsQuery")

        assert self._events_checked(query) == 630

    @parameterized.expand(
        [
            ("that_has_no_filter", [], 98, PASSED),
            ("whose_filter_keeps_too_few_sampled_events", [IS_PAID], 6, SKIPPED),
        ]
    )
    def test_samples_an_insight_with_more_events_than_the_sample_size(
        self,
        _name: str,
        properties: list[dict[str, Any]],
        sampled_events: int,
        bot_check_level: InsightDataCheckLevel,
    ) -> None:
        for person in range(10):
            self._events(2, distinct_id=f"person-{person}", event=WIDELY_SENT_EVENT, properties={"plan": "paid"})
        for person in range(10, 200):
            self._events(2, distinct_id=f"person-{person}", event=WIDELY_SENT_EVENT)
        flush_persons_and_events()

        with (
            patch(f"{CHECKS_MODULE}.SAMPLE_SIZE", 100),
            patch(f"{RESULTS_MODULE}.MIN_SAMPLED_EVENTS", 50),
        ):
            result = self._check(
                self._query([{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}], properties=properties)
            )

        sample = self._coverage(result).sample
        assert sample is not None
        assert (sample.rate, sample.events) == (0.25, sampled_events)
        assert {check.key: check.level for check in result.checks}[BOTS] == bot_check_level

    def test_checks_only_the_newest_days_of_a_longer_range(self) -> None:
        for days_ago in range(20):
            self._events(10, event=WIDELY_SENT_EVENT, days_ago=days_ago, properties={"$host": LOCAL_HOST})
        flush_persons_and_events()
        query = self._query(
            [{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}],
            kind="StickinessQuery",
            dateRange={"date_from": "-19d"},
        )

        with patch(f"{CHECKS_MODULE}.MAX_CHECKED_DAYS", 7):
            result = self._check(query)

        coverage = self._coverage(result)
        local = next(check for check in result.checks if check.key == LOCAL)
        assert (coverage.days_in_range, coverage.days_checked, coverage.events_checked) == (20, 7, 70)
        assert (local.events, local.result) == (
            70,
            "In the last 7 days, 100% of these events came from local development",
        )

    def test_counts_an_event_as_sent_twice_only_when_an_identical_one_came_under_100_ms_before(self) -> None:
        sent_twice_by_the_app = (timedelta(0), timedelta(milliseconds=20))
        clicked_twice_by_a_person = (timedelta(seconds=30), timedelta(seconds=30.3))
        for pair in range(10):
            sent_at = NOW - timedelta(days=2, minutes=pair)
            for gap in (*sent_twice_by_the_app, *clicked_twice_by_a_person):
                _create_event(team=self.team, event=WIDELY_SENT_EVENT, distinct_id="real", timestamp=sent_at + gap)
        flush_persons_and_events()

        result = self._check(self._query([{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}]))

        duplicates = next(check for check in result.checks if check.key == DUPLICATES)
        assert duplicates.events == 10

    @parameterized.expand(
        [
            ("unknown_event", [{"kind": "EventsNode", "event": "never sent"}], "no_events"),
            ("action_series", [{"kind": "ActionsNode", "id": 1}], "unsupported"),
        ]
    )
    def test_reports_why_nothing_was_checked(self, _name: str, series: list[dict[str, Any]], expected: str) -> None:
        result = self._check(self._query(series))

        assert result.status == expected
        assert {check.level for check in result.checks} == {"skipped"}

    def test_a_filter_that_cannot_run_raises_with_the_debug_modifier_on(self) -> None:
        query = self._query(properties=[{"type": "hogql", "key": "throwIf(1, 'stop') = 0"}], modifiers={"debug": True})

        with self.assertRaises(ExposedCHQueryError):
            self._check(query)

    def test_does_not_check_for_a_member_with_a_hidden_property(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        self._events(40, event=WIDELY_SENT_EVENT, properties={"plan": "paid"})
        flush_persons_and_events()
        query = self._query([{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}], properties=[IS_PAID])
        assert self._events_checked(query) == 40

        plan = PropertyDefinition.objects.create(team=self.team, name="plan", type=PropertyDefinition.Type.EVENT)
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                access_level=PropertyAccessLevel.NONE,
                property_definition_id=str(plan.id),
                organization_member_id=self.organization_membership.id,
            ),
        )

        assert self._check(query).status == "unsupported"
