import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any

import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.constants import AvailableFeature
from posthog.errors import CHQueryErrorQueryWasCancelled, ExposedCHQueryError
from posthog.exceptions import APIQueriesBudgetExceeded
from posthog.models import PersonalAPIKey, PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.team import Team

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.access_control.backend.models.access_control import AccessControl
from products.cohorts.backend.models.cohort import Cohort
from products.product_analytics.backend.facade.contracts import (
    InsightDataCheck,
    InsightDataChecks,
    InsightDataChecksCoverage,
    TeamEmailAccess,
)
from products.product_analytics.backend.facade.data_checks import run_insight_data_checks
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataChecksDepth,
    InsightDataCheckSkipReason,
)
from products.product_analytics.backend.facade.models import Insight
from products.product_analytics.backend.insight_data_check_days import newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    CheckedEvents,
    CountedEvents,
    InternalEvents,
    LocalEvents,
    SampledEvents,
    Skipped,
    evaluate_data_checks,
    status_of,
)
from products.product_analytics.backend.insight_data_check_team_emails import TeamEmails, team_email_pattern

from ee.clickhouse.materialized_columns.columns import materialize

PASSED = InsightDataCheckLevel.PASSED
WARNING = InsightDataCheckLevel.WARNING
PROBLEM = InsightDataCheckLevel.PROBLEM
SKIPPED = InsightDataCheckLevel.SKIPPED
INTERNAL = InsightDataCheckKey.INTERNAL_USERS
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
SENT_WITHOUT_A_PLAN = {"key": "plan", "value": "is_not_set", "operator": "is_not_set", "type": "event"}
ONE_STEP = [{"kind": "EventsNode", "event": EVENT}]
TWO_STEPS = [{"kind": "EventsNode", "event": EVENT}, {"kind": "EventsNode", "event": EVENT}]
SEVEN_DAYS = [date(2026, 3, 1) + timedelta(days=offset) for offset in range(7)]
CHECK_SCOPES = ["insight:read", "query:read"]
MEMBER_EMAIL = "founder@gmail.com"
VERIFIED_DOMAIN_EMAIL = "buyer@acme.example"


def checked(
    sampled_events: int,
    *,
    removed_by_filter: int = 0,
    missed_by_filter: int = 0,
    counted: bool = True,
    local: int = 0,
    bots: int = 0,
    repeats: int = 0,
    sample_rate: float = 1.0,
) -> CheckedEvents:
    counted_events: CountedEvents | Skipped = Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS)
    if counted:
        counted_events = CountedEvents(
            events=round(sampled_events / sample_rate),
            internal=InternalEvents(
                removed_by_filter=removed_by_filter,
                missed_by_filter=missed_by_filter,
                top_events=[],
                distinct_missed_emails=0,
                top_missed_emails=[],
                missed_emails=[],
            ),
        )
    return CheckedEvents(
        counted=counted_events,
        local=LocalEvents(count=local, distinct_hosts=1 if local else 0, top_hosts=[], top_events=[], hosts=[]),
        sample=SampledEvents(
            rate=sample_rate,
            events=sampled_events,
            distinct_ids=sampled_events,
            bot_events=bots,
            distinct_bots=0,
            top_bots=[],
            top_bot_events=[],
            repeated_events=repeats,
            top_repeated_events=[],
        ),
    )


class TestEvaluateDataChecks(SimpleTestCase):
    @parameterized.expand(
        [
            ("internal_small_share_is_a_warning", checked(10_000, removed_by_filter=200), {INTERNAL: WARNING}),
            ("internal_under_one_percent", checked(100_000, removed_by_filter=900), {}),
            ("internal_fifth_is_a_problem", checked(1000, missed_by_filter=200), {INTERNAL: PROBLEM}),
            ("local_tiny_share_still_counts", checked(1_000_000, local=60), {LOCAL: WARNING}),
            ("local_under_50_events", checked(100, local=49), {}),
            ("local_fifth_is_still_a_warning", checked(1000, local=200), {LOCAL: WARNING}),
            ("too_many_events_to_count_skips_only_internal_users", checked(1000, counted=False), {INTERNAL: SKIPPED}),
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
                "local_share_of_every_event_not_of_the_sample",
                checked(1000, local=300, sample_rate=0.1),
                {LOCAL: WARNING},
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
            ("internal_users_with_too_many_events_to_count", INTERNAL, checked(1000, counted=False), "too_many_events"),
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
                replace(checked(1000), sample=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT)),
                "read_limit",
            ),
        ]
    )
    def test_a_skipped_check_says_why(
        self, _name: str, key: InsightDataCheckKey, checked_events: CheckedEvents, reason: str
    ) -> None:
        skip_reasons = {check.key: check.skip_reason for check in evaluate_data_checks(checked_events)}
        assert skip_reasons[key] == reason

    @parameterized.expand(
        [
            ("filter_removes_them", 300, 0, "filter_internal_users"),
            ("filter_misses_too_few_to_change_it", 300, 10, "filter_internal_users"),
            ("filter_misses_the_team", 0, 300, "open_filter_settings"),
            ("filter_misses_some_of_the_team", 300, 100, "open_filter_settings"),
        ]
    )
    def test_internal_users_fix_turns_the_filter_on_unless_the_filter_misses_the_team(
        self, _name: str, removed_by_filter: int, missed_by_filter: int, action: str
    ) -> None:
        checks = evaluate_data_checks(
            checked(1000, removed_by_filter=removed_by_filter, missed_by_filter=missed_by_filter)
        )

        internal_users = next(check for check in checks if check.key == INTERNAL)
        assert (internal_users.events, internal_users.action) == (removed_by_filter + missed_by_filter, action)

    @parameterized.expand(
        [
            (
                "every_check_skipped",
                CheckedEvents(
                    counted=Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS),
                    local=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT),
                    sample=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT),
                ),
                "inconclusive",
            ),
            (
                "sample_hit_the_read_limit",
                replace(checked(1000), sample=Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT)),
                "partial",
            ),
            (
                "bot_check_not_needed_because_the_insight_filters_on_traffic_type",
                replace(checked(1000), insight_filters_traffic_type=True),
                "passed",
            ),
        ]
    )
    def test_status_says_whether_every_check_ran(
        self, _name: str, checked_events: CheckedEvents, expected: str
    ) -> None:
        assert status_of(evaluate_data_checks(checked_events)) == expected


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


class TestTeamEmailPattern(SimpleTestCase):
    @parameterized.expand(
        [
            ("company_domain", "sam@acme.example", True),
            ("subdomain_of_the_company_domain", "sam@eu.acme.example", True),
            ("member_on_a_public_provider", "founder@gmail.com", True),
            ("test_account", "test@gmail.com", True),
            ("numbered_test_account", "qa2@shop.example", True),
            ("test_alias", "maria+test1@shop.example", True),
            ("longer_domain_that_starts_the_same", "sam@acme.example.br", False),
            ("domain_that_ends_the_same", "sam@notacme.example", False),
            ("another_person_on_the_public_provider", "afounder@gmail.com", False),
            ("word_that_starts_with_test", "tester@shop.example", False),
            ("word_that_contains_test", "contest@shop.example", False),
            ("word_that_starts_with_demo", "demographics@shop.example", False),
            ("alias_that_is_not_a_test_word", "maria+news@shop.example", False),
        ]
    )
    def test_matches_the_team_and_test_accounts_only(self, _name: str, email: str, matches: bool) -> None:
        pattern = team_email_pattern(TeamEmails(domains=("acme.example",), addresses=("founder@gmail.com",)))

        assert bool(re.search(pattern, email)) == matches


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
        self._events(60, distinct_id="internal", person_properties={"email": "dev@posthog.com"})
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

    def _check(
        self, query: dict[str, Any], depth: InsightDataChecksDepth = InsightDataChecksDepth.QUICK
    ) -> InsightDataChecks:
        return run_insight_data_checks(
            query,
            team=self.team,
            user=self.user,
            email_access=TeamEmailAccess(member_emails=True, verified_domains=True, person_emails=True),
            depth=depth,
        )

    def _internal_users(self, result: InsightDataChecks) -> InsightDataCheck:
        return next(check for check in result.checks if check.key == INTERNAL)

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
            "internal_users": ("warning", 60),
            "local_development": ("warning", 60),
            "bot_traffic": ("warning", 60),
            "duplicate_events": ("warning", 110),
        }
        assert {
            check.key: (check.top_events, check.top_hosts, check.distinct_hosts, check.top_bots)
            for check in result.checks
        } == {
            "internal_users": ([EVENT], [], None, []),
            "local_development": ([EVENT], [LOCAL_HOST], 1, []),
            "bot_traffic": ([EVENT], [], None, ["Google fetcher", "Googlebot"]),
            "duplicate_events": ([EVENT], [], None, []),
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
            ("events_on_every_day", range(20), "warning", 70),
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
            ("insight_without_the_filter", True, {}, (60, "filter_internal_users", 60, 0)),
            ("insight_with_the_filter", True, {"filterTestAccounts": True}, (0, None, 0, 0)),
            ("project_without_a_filter", False, {}, (60, "open_filter_settings", 0, 60)),
        ]
    )
    def test_internal_users_check_follows_the_filter_in_place(
        self,
        _name: str,
        project_has_a_filter: bool,
        source: dict[str, Any],
        expected: tuple[int, str | None, int, int],
    ) -> None:
        if not project_has_a_filter:
            self.team.test_account_filters = []
            self.team.save()

        internal_users = self._internal_users(self._check(self._query(**source)))

        assert (
            internal_users.events,
            internal_users.action,
            internal_users.removed_by_filter,
            internal_users.missed_by_filter,
        ) == expected

    @parameterized.expand(
        [
            ("persons_are_on_events", "person_id_override_properties_on_events"),
            ("persons_are_not_on_events", "disabled"),
            ("persons_are_joined", "person_id_override_properties_joined"),
        ]
    )
    def test_internal_users_suggested_rule_removes_the_emails_it_names(
        self, _name: str, persons_on_events_mode: str
    ) -> None:
        _create_person(team=self.team, distinct_ids=["qa"], properties={"email": "QA@Example.com"})
        self._events(60, distinct_id="qa", person_properties={"email": "Test@Example.com"})
        flush_persons_and_events()
        modifiers = {"personsOnEventsMode": persons_on_events_mode}
        rule = self._internal_users(self._check(self._query(modifiers=modifiers))).filter_to_add
        assert rule is not None
        self.team.test_account_filters = [
            *self.team.test_account_filters,
            {"key": rule.key, "type": rule.type, "operator": rule.operator, "value": rule.value},
        ]
        self.team.save()

        result = self._check(self._query(filterTestAccounts=True, modifiers=modifiers))

        assert self._internal_users(result).missed_by_filter == 0

    @parameterized.expand(
        [
            ("suggested_rule_with_the_insight_filter_off", {}),
            ("suggested_rule_with_the_insight_filter_on", {"filterTestAccounts": True}),
        ]
    )
    def test_local_development_check_counts_only_the_local_events_the_filter_keeps(
        self, _name: str, source: dict[str, Any]
    ) -> None:
        found = next(check for check in self._check(self._query(**source)).checks if check.key == LOCAL)
        assert found.filter_to_add is not None
        rule = found.filter_to_add
        self.team.test_account_filters = [
            *self.team.test_account_filters,
            {"key": rule.key, "type": rule.type, "operator": rule.operator, "value": rule.value},
        ]
        self.team.save()

        local = next(check for check in self._check(self._query(**source)).checks if check.key == LOCAL)

        assert (local.events, local.skip_reason) == (0, None)

    @parameterized.expand(
        [("without_a_project_filter", None), ("with_a_person_filter", "person"), ("with_a_cohort_filter", "cohort")]
    )
    def test_keeps_events_without_a_person_when_persons_are_not_on_events(
        self, _name: str, filter_type: str | None
    ) -> None:
        if filter_type is None:
            self.team.test_account_filters = []
        elif filter_type == "cohort":
            staff = Cohort.objects.create(team=self.team, name="staff", is_static=True)
            self.team.test_account_filters = [{"key": "id", "type": "cohort", "value": staff.id, "operator": "not_in"}]
        self.team.save()
        self._events(20, distinct_id="no person", event=WIDELY_SENT_EVENT)
        flush_persons_and_events()
        query = self._query(
            [{"kind": "EventsNode", "event": WIDELY_SENT_EVENT}],
            kind="TrendsQuery",
            modifiers={"personsOnEventsMode": "disabled"},
        )

        result = self._check(query)

        assert (self._coverage(result).events_checked, self._internal_users(result).events) == (20, 0)

    @parameterized.expand(
        [
            ("persons_are_not_on_events", "disabled", 80),
            ("persons_are_joined", "person_id_override_properties_joined", 80),
            ("persons_are_on_events", "person_id_override_properties_on_events", 60),
            (
                "filter_with_a_subquery",
                "disabled",
                80,
                "person.properties.email NOT ILIKE '%@posthog.com' "
                "AND person_id NOT IN (SELECT person_id FROM person_distinct_ids WHERE distinct_id = 'nobody')",
            ),
        ]
    )
    def test_reads_person_properties_from_where_the_insight_reads_them(
        self, _name: str, persons_on_events_mode: str, internal_user_events: int, hogql_filter: str | None = None
    ) -> None:
        if hogql_filter is not None:
            self.team.test_account_filters = [{"type": "hogql", "key": hogql_filter}]
            self.team.save()
        _create_person(team=self.team, distinct_ids=["joined later"], properties={"email": "new@posthog.com"})
        self._events(20, distinct_id="joined later", person_properties={"email": "before@example.com"})
        flush_persons_and_events()

        result = self._check(self._query(modifiers={"personsOnEventsMode": persons_on_events_mode}))

        assert self._internal_users(result).events == internal_user_events

    @parameterized.expand([("on_a_deleted_cohort", "cohort"), ("on_a_field_that_does_not_exist", "hogql")])
    def test_reports_the_other_checks_when_the_projects_filter_cannot_run(self, _name: str, filter_type: str) -> None:
        if filter_type == "cohort":
            deleted = Cohort.objects.create(team=self.team, name="deleted", deleted=True)
            self.team.test_account_filters = [
                {"key": "id", "type": "cohort", "value": deleted.id, "operator": "not_in"}
            ]
        else:
            self.team.test_account_filters = [{"type": "hogql", "key": "timestamp.day"}]
        self.team.save()

        result = self._check(self._query())

        local = next(check for check in result.checks if check.key == LOCAL)
        assert (local.level, local.events) == ("warning", 60)
        assert self._internal_users(result).skip_reason == "invalid_filter"

    @parameterized.expand(
        [
            ("unknown_event", [{"kind": "EventsNode", "event": "never sent"}], 1_000_000_000, "quick", "no_events"),
            ("read_limit_reached_while_sizing", ONE_STEP, 1, "quick", "inconclusive"),
            ("full_check_past_its_deadline", ONE_STEP, 1_000_000_000, "full", "inconclusive"),
        ]
    )
    @patch(f"{CHECKS_MODULE}.FULL_MAX_EXECUTION_SECONDS", 0)
    def test_reports_why_nothing_was_checked(
        self, _name: str, series: list[dict[str, Any]], max_bytes_read: int, depth: str, expected: str
    ) -> None:
        with patch(f"{CHECKS_MODULE}.MAX_BYTES_READ", max_bytes_read):
            result = self._check(self._query(series), InsightDataChecksDepth(depth))

        assert result.status == expected
        assert {check.level for check in result.checks} == {"skipped"}

    # The native events table reads a property from a subcolumn of its own, so a property filter reads little there.
    @parameterized.expand(
        [
            ("properties_with_columns_of_their_own", [], None, 10_000, ("warning", "warning")),
            (
                "a_filter_on_a_property_without_a_column",
                [SENT_WITHOUT_A_PLAN],
                None,
                10_000,
                ("on_request", "warning"),
            ),
            (
                "too_few_events_to_read_a_lot_even_from_large_events",
                [SENT_WITHOUT_A_PLAN],
                None,
                0,
                ("warning", "warning"),
            ),
            ("asked_for_in_the_request_body", [SENT_WITHOUT_A_PLAN], "body", 10_000, ("warning", "warning")),
            ("asked_for_on_a_saved_insight", [SENT_WITHOUT_A_PLAN], "saved_insight", 10_000, ("warning", "warning")),
        ]
    )
    @patch(f"{CHECKS_MODULE}.MAX_ESTIMATED_BYTES", 1)
    def test_runs_the_checks_that_would_read_a_lot_only_on_request(
        self,
        _name: str,
        properties: list[dict[str, Any]],
        asked_for: str | None,
        max_json_bytes_per_event: int,
        status_by_events_schema: tuple[str, str],
    ) -> None:
        legacy_status, native_status = status_by_events_schema
        expected_status = native_status if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else legacy_status
        self.enterContext(patch(f"{CHECKS_MODULE}.MAX_JSON_BYTES_PER_EVENT", max_json_bytes_per_event))
        self.addCleanup(cleanup_materialized_columns)
        materialize("events", "email", table_column="person_properties")
        # A lifecycle chart filters on this property, which production reads from a column of its own.
        materialize("events", "$process_person_profile")
        query = self._query(
            properties=properties, modifiers={"personsOnEventsMode": "person_id_override_properties_on_events"}
        )

        if asked_for == "saved_insight":
            insight = Insight.objects.create(team=self.team, query=query)
            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/data_checks/?depth=full")
        else:
            body = {"query": query, "depth": "full"} if asked_for == "body" else {"query": query}
            response = self.client.post(f"/api/projects/{self.team.id}/insights/data_checks/", body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["status"] == expected_status

    def test_a_filter_that_cannot_run_raises_with_the_debug_modifier_on(self) -> None:
        query = self._query(properties=[{"type": "hogql", "key": "throwIf(1, 'stop') = 0"}], modifiers={"debug": True})

        with self.assertRaises(ExposedCHQueryError):
            self._check(query)

    @parameterized.expand(
        [
            ("a_property_the_checks_read", "$host", PropertyDefinition.Type.EVENT, "unsupported", None),
            ("a_property_the_checks_do_not_read", "plan", PropertyDefinition.Type.EVENT, "warning", None),
            ("the_email_of_a_person", "email", PropertyDefinition.Type.PERSON, "warning", "hidden_property"),
            ("an_event_property_named_email", "email", PropertyDefinition.Type.EVENT, "warning", None),
        ]
    )
    def test_a_hidden_property_stops_the_checks_only_when_they_read_it(
        self,
        _name: str,
        hidden_property: str,
        property_type: PropertyDefinition.Type,
        status: str,
        internal_users_skip_reason: str | None,
    ) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(team=self.team, name=hidden_property, type=property_type)
        upsert_property_access_control(
            team_id=self.team.id,
            created_by_id=self.user.id,
            input=UpsertPropertyAccessControlInput(
                access_level=PropertyAccessLevel.NONE,
                property_definition_id=str(definition.id),
                organization_member_id=self.organization_membership.id,
            ),
        )

        result = self._check(self._query())

        assert result.status == status
        assert self._internal_users(result).skip_reason == internal_users_skip_reason

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
        [
            ("member_for_a_session_that_may_see_them", MEMBER_EMAIL, None, True, (80, [MEMBER_EMAIL])),
            (
                "member_for_a_token_with_the_member_scope",
                MEMBER_EMAIL,
                [*CHECK_SCOPES, "person:read", "organization_member:read"],
                True,
                (80, [MEMBER_EMAIL]),
            ),
            (
                "member_for_a_token_without_the_member_scope",
                MEMBER_EMAIL,
                [*CHECK_SCOPES, "person:read"],
                True,
                (0, []),
            ),
            ("member_for_a_session_that_may_not_see_them", MEMBER_EMAIL, None, False, (0, [])),
            (
                "member_for_a_token_without_the_person_scope",
                MEMBER_EMAIL,
                [*CHECK_SCOPES, "organization_member:read"],
                True,
                (80, []),
            ),
            (
                "verified_domain_for_a_token_with_the_organization_scope",
                VERIFIED_DOMAIN_EMAIL,
                [*CHECK_SCOPES, "person:read", "organization:read"],
                True,
                (80, [VERIFIED_DOMAIN_EMAIL]),
            ),
            (
                "verified_domain_for_a_token_without_the_organization_scope",
                VERIFIED_DOMAIN_EMAIL,
                [*CHECK_SCOPES, "person:read", "organization_member:read"],
                True,
                (0, []),
            ),
            (
                "member_for_a_token_confined_to_the_project",
                MEMBER_EMAIL,
                [*CHECK_SCOPES, "person:read", "organization_member:read", "organization:read"],
                True,
                (0, []),
                True,
            ),
        ]
    )
    def test_matches_a_team_email_only_for_a_caller_who_may_read_it(
        self,
        _name: str,
        email: str,
        scopes: list[str] | None,
        member_is_visible: bool,
        expected: tuple[int, list[str]],
        confined_to_the_project: bool = False,
    ) -> None:
        self._create_user(MEMBER_EMAIL)
        OrganizationDomain.objects.create(organization=self.organization, domain="acme.example", verified_at=NOW)
        _create_person(team=self.team, distinct_ids=["teammate"], properties={"email": email})
        self._events(80, distinct_id="teammate", person_properties={"email": email})
        flush_persons_and_events()
        if not member_is_visible:
            self._limit_the_member_list_to_project_members()
        headers = {}
        if scopes is not None:
            headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}
            if confined_to_the_project:
                PersonalAPIKey.objects.filter(user=self.user).update(scoped_teams=[self.team.id])
            self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/data_checks/",
            {"query": self._query(filterTestAccounts=True)},
            format="json",
            headers=headers,
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        internal_users = next(check for check in response.json()["checks"] if check["key"] == INTERNAL)
        rule = internal_users["filter_to_add"]
        events, named_emails = expected
        assert (internal_users["events"], internal_users["top_emails"], rule["value"] if rule else []) == (
            events,
            named_emails,
            named_emails,
        )

    def _limit_the_member_list_to_project_members(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.members_can_see_org_members = False
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )

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

    def test_tags_the_check_queries_with_the_client_query_id_so_the_client_can_cancel_them(self) -> None:
        tagged: list[str | None] = []

        def cancelled(*args: Any, **kwargs: Any) -> None:
            tagged.append(get_query_tag_value("client_query_id"))
            raise CHQueryErrorQueryWasCancelled("Query was cancelled", code=394, code_name="query_was_cancelled")

        with patch(f"{CHECKS_MODULE}.execute_hogql_query", side_effect=cancelled):
            response = self.client.post(
                f"/api/projects/{self.team.id}/insights/data_checks/",
                {"query": self._query(), "client_query_id": "checks-run-1"},
                format="json",
            )

        assert tagged == ["checks-run-1"]
        assert response.status_code == 499, response.content
        assert response.content == b""
