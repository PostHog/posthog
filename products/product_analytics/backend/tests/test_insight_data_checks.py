from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.errors import ExposedCHQueryError
from posthog.exceptions import APIQueriesBudgetExceeded
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.access_control.backend.models.access_control import AccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.facade.contracts import InsightDataChecks, InsightDataChecksCoverage
from products.product_analytics.backend.facade.data_checks import run_insight_data_checks
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataCheckSkipReason,
)
from products.product_analytics.backend.facade.models import Insight
from products.product_analytics.backend.insight_data_check_days import newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    CheckedEvents,
    LocalEvents,
    SampledEvents,
    Skipped,
    evaluate_data_checks,
    status_of,
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
ORDINARY_BROWSER_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AcmeBrowser/1.0"
LOCAL_HOST = "localhost:8010"
CHECKS_MODULE = "products.product_analytics.backend.insight_data_checks"
RESULTS_MODULE = "products.product_analytics.backend.insight_data_check_results"
ROUTE_MODULE = "products.product_analytics.backend.presentation.insight"
ON_LOCAL_HOST = {"key": "$host", "value": [LOCAL_HOST], "operator": "exact", "type": "event"}
FROM_A_BOT = {"key": "$raw_user_agent", "value": [BOT_USER_AGENT], "operator": "exact", "type": "event"}
NOT_A_BOT = {"key": "$virt_traffic_type", "value": ["Bot"], "operator": "is_not", "type": "event"}
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
) -> CheckedEvents:
    too_many_to_count = Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS)
    return CheckedEvents(
        local=too_many_to_count if local is None else LocalEvents(count=local, top_hosts=[], top_events=[]),
        sample=SampledEvents(
            rate=sample_rate,
            events=sampled_events,
            distinct_ids=sampled_events,
            bot_events=bots,
            top_bots=[],
            top_bot_events=[],
            repeated_events=repeats,
            top_repeated_events=[],
        ),
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
            (
                "local_with_an_empty_partial_sample_is_at_most_a_warning",
                checked(0, local=60, sample_rate=0.1),
                {LOCAL: WARNING, BOTS: SKIPPED, DUPLICATES: SKIPPED},
            ),
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
            ("local_with_too_many_events_to_count", LOCAL, checked(1000, local=None), "too_many_events"),
            ("bots_with_too_few_sampled_events", BOTS, checked(500, sample_rate=0.1), "too_few_sampled_events"),
            (
                "bots_when_the_insight_filters_on_traffic_type",
                BOTS,
                replace(checked(1000), insight_filters_traffic_type=True),
                "filtered_by_traffic_type",
            ),
            (
                "duplicates_whose_sample_hit_the_read_limit",
                DUPLICATES,
                CheckedEvents(
                    local=LocalEvents(count=0, top_hosts=[], top_events=[]),
                    sample=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT),
                ),
                "read_limit",
            ),
        ]
    )
    def test_a_skipped_check_says_why(
        self, _name: str, key: InsightDataCheckKey, checked_events: CheckedEvents, reason: str
    ) -> None:
        skip_reasons = {check.key: check.skip_reason for check in evaluate_data_checks(checked_events)}
        assert skip_reasons[key] == reason

    def test_status_is_inconclusive_when_every_check_is_skipped(self) -> None:
        checks = evaluate_data_checks(
            CheckedEvents(
                local=Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS),
                sample=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT),
            )
        )

        assert status_of(checks) == "inconclusive"


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
        assert {check.key: (check.top_events, check.top_hosts, check.top_bots) for check in result.checks} == {
            "local_development": ([EVENT], [LOCAL_HOST], []),
            "bot_traffic": ([EVENT], [], ["Google fetcher", "Googlebot"]),
            "duplicate_events": ([EVENT], [], []),
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

    @parameterized.expand(
        [
            ("events_on_every_day", range(20), "problem", 70),
            ("no_events_on_the_newest_days", range(10, 20), "no_events", 0),
        ]
    )
    def test_checks_only_the_newest_days_of_a_longer_range(
        self, _name: str, days_with_events: range, status: str, events_checked: int
    ) -> None:
        for days_ago in days_with_events:
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
        assert (result.status, coverage.days_in_range, coverage.days_checked) == (status, 20, 7)
        assert coverage.events_checked == events_checked

    @parameterized.expand(
        [
            ("insight_without_a_traffic_type_filter", [], 620, 60, None),
            ("insight_that_filters_on_traffic_type", [NOT_A_BOT], 540, None, "filtered_by_traffic_type"),
        ]
    )
    def test_applies_a_projects_own_bot_rules_only_to_the_insights_filters(
        self,
        _name: str,
        properties: list[dict[str, Any]],
        events_checked: int,
        bot_events: int | None,
        bot_skip_reason: str | None,
    ) -> None:
        self._events(20, properties={"$raw_user_agent": ORDINARY_BROWSER_USER_AGENT})
        flush_persons_and_events()
        self.team.modifiers = {
            "customBotDefinitions": [
                {
                    "id": "acme",
                    "name": "Acme",
                    "combiner": "OR",
                    "items": [{"id": "1", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBrowser"}],
                }
            ]
        }
        self.team.save()

        result = self._check(self._query(properties=properties))

        bots = next(check for check in result.checks if check.key == BOTS)
        assert self._coverage(result).events_checked == events_checked
        assert (bots.events, bots.skip_reason) == (bot_events, bot_skip_reason)

    def test_ignores_the_interval_a_lifecycle_chart_reads_before_its_range(self) -> None:
        self._events(10, event=WIDELY_SENT_EVENT, days_ago=8, properties={"$host": LOCAL_HOST})
        flush_persons_and_events()
        query = self._query([{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}], dateRange={"date_from": "-7d"})

        assert self._check(query).status == "no_events"

    def test_counts_an_event_as_sent_twice_only_when_an_identical_one_came_under_100_ms_before(self) -> None:
        sent_twice_by_the_app = (timedelta(0), timedelta(milliseconds=20))
        clicked_twice_by_a_person = (timedelta(seconds=30), timedelta(seconds=30.3))
        for pair in range(10):
            sent_at = NOW - timedelta(days=2, minutes=pair)
            for gap in (*sent_twice_by_the_app, *clicked_twice_by_a_person):
                _create_event(team=self.team, event=WIDELY_SENT_EVENT, distinct_id="real", timestamp=sent_at + gap)
        flush_persons_and_events()

        never_sent_twice = {"kind": "EventsNode", "event": SENT_ON_THE_FREE_PLAN}
        query = self._query(
            [{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}, never_sent_twice], kind="StickinessQuery"
        )

        result = self._check(query)

        duplicates = next(check for check in result.checks if check.key == DUPLICATES)
        assert (duplicates.events, duplicates.top_events) == (10, [WIDELY_SENT_EVENT])

    @parameterized.expand(
        [
            ("unknown_event", [{"kind": "EventsNode", "event": "never sent"}], 1_000_000_000, "no_events"),
            ("action_series", [{"kind": "ActionsNode", "id": 1}], 1_000_000_000, "unsupported"),
            ("read_limit_reached_while_sizing", ONE_STEP, 1, "inconclusive"),
        ]
    )
    def test_reports_why_nothing_was_checked(
        self, _name: str, series: list[dict[str, Any]], max_bytes_read_per_shard: int, expected: str
    ) -> None:
        with patch(f"{CHECKS_MODULE}.MAX_BYTES_READ_PER_SHARD", max_bytes_read_per_shard):
            result = self._check(self._query(series))

        assert result.status == expected
        assert {check.level for check in result.checks} == {"skipped"}

    def test_a_filter_that_cannot_run_raises_with_the_debug_modifier_on(self) -> None:
        query = self._query(properties=[{"type": "hogql", "key": "throwIf(1, 'stop') = 0"}], modifiers={"debug": True})

        with self.assertRaises(ExposedCHQueryError):
            self._check(query)

    @parameterized.expand(
        [
            ("a_property_the_checks_read", "$host", "unsupported"),
            ("a_property_the_checks_do_not_read", "plan", "warning"),
        ]
    )
    def test_a_hidden_property_stops_the_checks_only_when_they_read_it(
        self, _name: str, hidden_property: str, status: str
    ) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=hidden_property, type=PropertyDefinition.Type.EVENT
        )
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                access_level=PropertyAccessLevel.NONE,
                property_definition_id=str(definition.id),
                organization_member_id=self.organization_membership.id,
            ),
        )

        assert self._check(self._query()).status == status

    @parameterized.expand(
        [
            ("found_by_numeric_id", "id", True, {"events_checked": 540}),
            ("found_by_short_id", "short_id", True, {"events_checked": 540}),
            ("without_a_stored_query", "id", False, {"status": "unsupported"}),
        ]
    )
    def test_checks_the_query_a_saved_insight_stores(
        self, _name: str, reference: str, stores_a_query: bool, expected: dict[str, Any]
    ) -> None:
        insight = Insight.objects.create(
            team=self.team,
            query=self._query(filterTestAccounts=True) if stores_a_query else None,
            filters={} if stores_a_query else {"insight": "LIFECYCLE", "events": [{"id": EVENT}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{getattr(insight, reference)}/data_checks/")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        summary = {"status": body["status"], "events_checked": body["coverage"] and body["coverage"]["events_checked"]}
        assert {key: summary[key] for key in expected} == expected

    def test_does_not_check_an_insight_from_another_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        insight = Insight.objects.create(team=other_team, query=self._query())

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/data_checks/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("without_the_query_scope", ["insight:read"], status.HTTP_403_FORBIDDEN),
            ("with_the_query_scope", ["insight:read", "query:read"], status.HTTP_200_OK),
        ]
    )
    def test_an_api_key_needs_the_query_scope_to_check_a_query_that_is_not_saved(
        self, _name: str, scopes: list[str], expected: int
    ) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/data_checks/",
            {"query": self._query()},
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == expected, response.content

    @parameterized.expand(
        [("api_key", True, status.HTTP_429_TOO_MANY_REQUESTS), ("session", False, status.HTTP_200_OK)]
    )
    def test_an_api_key_checks_within_the_query_read_budget(self, _name: str, uses_a_key: bool, expected: int) -> None:
        headers = {}
        if uses_a_key:
            headers = {
                "authorization": f"Bearer {self.create_personal_api_key_with_scopes(['insight:read', 'query:read'])}"
            }
            self.client.logout()

        with patch(f"{ROUTE_MODULE}.enforce_api_queries_budget", side_effect=APIQueriesBudgetExceeded(wait=5)):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/data_checks/",
                {"query": self._query()},
                format="json",
                headers=headers,
            )

        assert response.status_code == expected, response.content

    def test_a_member_without_query_access_can_only_check_a_saved_insight(self) -> None:
        insight = Insight.objects.create(team=self.team, query=self._query())
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team, resource="query", organization_member=self.organization_membership, access_level="none"
        )

        not_saved = self.client.post(
            f"/api/projects/{self.team.id}/insights/data_checks/", {"query": self._query()}, format="json"
        )
        saved = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/data_checks/")

        assert not_saved.status_code == status.HTTP_403_FORBIDDEN, not_saved.content
        assert saved.status_code == status.HTTP_200_OK, saved.content

    @parameterized.expand(
        [
            ("without_a_query", None),
            ("with_a_filter_that_is_not_valid_sql", {"properties": [{"type": "hogql", "key": "1 +"}]}),
            (
                "with_a_filter_on_a_field_that_does_not_exist",
                {"properties": [{"type": "hogql", "key": "timestamp.day"}]},
            ),
        ]
    )
    def test_rejects_a_request_it_cannot_check(self, _name: str, source: dict[str, Any] | None) -> None:
        body = {} if source is None else {"query": self._query(**source)}

        response = self.client.post(f"/api/projects/{self.team.id}/insights/data_checks/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
