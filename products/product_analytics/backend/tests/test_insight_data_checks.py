from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
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
from products.product_analytics.backend.facade.contracts import InsightDataChecks
from products.product_analytics.backend.facade.data_checks import run_insight_data_checks
from products.product_analytics.backend.facade.enums import InsightDataCheckKey, InsightDataCheckLevel
from products.product_analytics.backend.insight_data_checks import DataCheckCounts, evaluate_data_checks

PASSED = InsightDataCheckLevel.PASSED
WARNING = InsightDataCheckLevel.WARNING
PROBLEM = InsightDataCheckLevel.PROBLEM
NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
EVENT = "signed up"
WIDELY_SENT_EVENT = "opened app"
SENT_ON_THE_FREE_PLAN = "invited teammate"
BOT_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"
CRAWLER_IP = "66.249.84.5"
LOCAL_HOST = "localhost:8010"
CHECKS_MODULE = "products.product_analytics.backend.insight_data_checks"
ON_LOCAL_HOST = {"key": "$host", "value": [LOCAL_HOST], "operator": "exact", "type": "event"}
FROM_A_BOT = {"key": "$raw_user_agent", "value": [BOT_USER_AGENT], "operator": "exact", "type": "event"}
IS_PAID = {"key": "plan", "value": ["paid"], "operator": "exact", "type": "event"}
HAS_NO_PLAN_TODAY = {"key": "plan", "value": "is_not_set", "operator": "is_not_set", "type": "person"}
ONE_STEP = [{"kind": "EventsNode", "event": EVENT}]
TWO_STEPS = [{"kind": "EventsNode", "event": EVENT}, {"kind": "EventsNode", "event": EVENT}]


def counts(
    events: int,
    *,
    local: int = 0,
    bots: int = 0,
    duplicates: int = 0,
    sample_rate: float = 1.0,
) -> DataCheckCounts:
    return DataCheckCounts(
        events=events,
        local_events=local,
        bot_events=bots,
        distinct_events=events - duplicates,
        sample_rate=sample_rate,
    )


class TestEvaluateDataChecks(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "local_tiny_share_still_counts",
                InsightDataCheckKey.LOCAL_DEVELOPMENT,
                counts(1000000, local=60),
                WARNING,
            ),
            ("local_under_50_events", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(100, local=49), PASSED),
            (
                "local_under_50_sampled_events_but_over_50_in_the_insight",
                InsightDataCheckKey.LOCAL_DEVELOPMENT,
                counts(1000000, local=10, sample_rate=0.01),
                WARNING,
            ),
            ("local_fifth_is_a_problem", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(1000, local=200), PROBLEM),
            ("bots_small_share_is_a_warning", InsightDataCheckKey.BOT_TRAFFIC, counts(10000, bots=200), WARNING),
            (
                "bots_under_50_sampled_events_but_over_50_in_the_insight",
                InsightDataCheckKey.BOT_TRAFFIC,
                counts(1000, bots=40, sample_rate=0.1),
                WARNING,
            ),
            ("bots_under_one_percent", InsightDataCheckKey.BOT_TRAFFIC, counts(100000, bots=500), PASSED),
            ("duplicates_under_100_events", InsightDataCheckKey.DUPLICATE_EVENTS, counts(1000, duplicates=99), PASSED),
            (
                "duplicates_under_five_percent",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=400),
                PASSED,
            ),
            (
                "duplicates_over_both_floors",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=600),
                WARNING,
            ),
            (
                "duplicates_under_100_sampled_events_but_over_100_in_the_insight",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(1000, duplicates=80, sample_rate=0.01),
                WARNING,
            ),
            (
                "duplicates_fifth_is_a_problem",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(1000, duplicates=250),
                PROBLEM,
            ),
        ]
    )
    def test_level_follows_count_and_share(
        self, _name: str, key: InsightDataCheckKey, check_counts: DataCheckCounts, expected: InsightDataCheckLevel
    ) -> None:
        checks = evaluate_data_checks(check_counts)
        assert {check.key: check.level for check in checks} == {
            **dict.fromkeys(InsightDataCheckKey, PASSED),
            key: expected,
        }

    @parameterized.expand(
        [
            ("every_event_read", 1.0, "66 of these events came from local development"),
            ("sample_read", 0.01, "About 6,600 of these events came from local development"),
        ]
    )
    def test_a_count_from_a_sample_is_scaled_up_to_the_whole_insight(
        self, _name: str, sample_rate: float, expected: str
    ) -> None:
        checks = evaluate_data_checks(counts(1000000, local=66, sample_rate=sample_rate))
        results = {check.key: check.result for check in checks}
        assert results[InsightDataCheckKey.LOCAL_DEVELOPMENT] == expected


@time_machine.travel(NOW, tick=False)
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

    def test_counts_each_problem_in_the_events_the_insight_reads(self) -> None:
        result = self._check(self._query())

        assert result.status == "warning"
        assert (result.events_checked, result.sample_rate) == (600, 1)
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
        assert self._check(self._query(**source)).events_checked == events_checked

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

        checks = self._check(query)

        assert checks.events_checked == events_checked

    def test_a_first_time_series_checks_only_the_events_in_its_date_range(self) -> None:
        query = self._query([{"kind": "EventsNode", "event": EVENT, "math": "first_time_for_user"}], kind="TrendsQuery")

        checks = self._check(query)

        assert checks.events_checked == 630

    @parameterized.expand(
        [
            ("that_has_no_filter", [], 100, 0.25, 98),
            ("whose_filter_keeps_fewer_events_than_the_limit", [IS_PAID], 100, 1, 20),
            ("whose_filter_keeps_more_events_than_the_limit", [IS_PAID], 10, 0.5, 12),
        ]
    )
    def test_reads_a_sample_of_an_insight_with_more_events_than_the_limit(
        self,
        _name: str,
        properties: list[dict[str, Any]],
        max_checked_events: int,
        sample_rate: float,
        events_checked: int,
    ) -> None:
        for person in range(10):
            self._events(2, distinct_id=f"person-{person}", event=WIDELY_SENT_EVENT, properties={"plan": "paid"})
        for person in range(10, 200):
            self._events(2, distinct_id=f"person-{person}", event=WIDELY_SENT_EVENT)
        flush_persons_and_events()

        with (
            patch(f"{CHECKS_MODULE}.MAX_CHECKED_EVENTS", max_checked_events),
            patch(f"{CHECKS_MODULE}.MIN_CHECKED_EVENTS", 40),
        ):
            result = self._check(
                self._query([{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}], properties=properties)
            )

        assert (result.sample_rate, result.events_checked) == (sample_rate, events_checked)

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
        assert self._check(query).events_checked == 40

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
