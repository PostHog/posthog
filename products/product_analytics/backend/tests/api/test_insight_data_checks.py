from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.team import Team

from products.access_control.backend.facade.api import upsert_property_access_control
from products.access_control.backend.facade.contracts import PropertyAccessLevel, UpsertPropertyAccessControlInput
from products.product_analytics.backend.facade.models import Insight

NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
EVENT = "signed up"
WIDELY_SENT_EVENT = "opened app"
BOT_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0"
CRAWLER_IP = "66.249.84.5"
LOCAL_HOST = "localhost:8010"
CHECKS_MODULE = "products.product_analytics.backend.insight_data_checks"
ON_LOCAL_HOST = {"key": "$host", "value": [LOCAL_HOST], "operator": "exact", "type": "event"}
FROM_A_BOT = {"key": "$raw_user_agent", "value": [BOT_USER_AGENT], "operator": "exact", "type": "event"}


@time_machine.travel(NOW, tick=False)
class TestInsightDataChecksAPI(ClickhouseTestMixin, APIBaseTest):
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
            self._events(2, same_second=True, properties={"$current_url": "https://example.com/pricing"})
        self._events(50, event="another event", properties={"$host": LOCAL_HOST})
        self._events(50, days_ago=70, properties={"$host": LOCAL_HOST})
        flush_persons_and_events()

    def _events(
        self,
        count: int,
        *,
        distinct_id: str = "real",
        event: str = EVENT,
        days_ago: int = 1,
        same_second: bool = False,
        properties: dict[str, Any] | None = None,
    ) -> None:
        for _ in range(count):
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=NOW - timedelta(days=days_ago, seconds=self._second),
                properties=properties or {},
            )
            if not same_second:
                self._second += 1
        self._second += 1

    def _query(self, series: dict[str, Any] | list[dict[str, Any]] | None = None, **source: Any) -> dict[str, Any]:
        return {
            "kind": "InsightVizNode",
            "source": {
                # Not a trends query: the repo's crossing scan reads one in a test as a run of web analytics code.
                "kind": "LifecycleQuery",
                "series": series if isinstance(series, list) else [series or {"kind": "EventsNode", "event": EVENT}],
                "dateRange": {"date_from": "-60d"},
                **source,
            },
        }

    def _check(self, query: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/data_checks/", {"query": query}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_counts_each_problem_in_the_events_the_insight_reads(self) -> None:
        result = self._check(self._query())

        assert result["status"] == "warning"
        assert (result["events_checked"], result["sample_rate"]) == (600, 1)
        assert {check["key"]: (check["level"], check["events"]) for check in result["checks"]} == {
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
                {"series": {"kind": "EventsNode", "event": EVENT, "properties": [ON_LOCAL_HOST]}},
                60,
            ),
            (
                "a_filter_on_each_series",
                {
                    "series": [
                        {"kind": "EventsNode", "event": EVENT, "properties": [ON_LOCAL_HOST]},
                        {"kind": "EventsNode", "properties": [FROM_A_BOT]},
                    ]
                },
                90,
            ),
            (
                "series_that_counts_groups",
                {
                    "kind": "StickinessQuery",
                    "series": {
                        "kind": "EventsNode",
                        "event": EVENT,
                        "math": "unique_group",
                        "math_group_type_index": 0,
                    },
                },
                60,
            ),
            ("shorter_date_range", {"dateRange": {"date_from": "-12h"}}, 0),
            ("date_range_without_a_start", {"dateRange": {}}, 600),
            ("weekdays", {"kind": "StickinessQuery", "dateRange": {"date_from": "-80d", "daysOfWeek": [2]}}, 50),
        ]
    )
    def test_checks_only_what_the_insights_own_filters_keep(
        self, _name: str, source: dict[str, Any], events_checked: int
    ) -> None:
        assert self._check(self._query(**source))["events_checked"] == events_checked

    @parameterized.expand(
        [
            ("that_has_no_filter", [], 0.25, range(1, 400)),
            (
                "whose_filter_keeps_few_of_them",
                [{"key": "plan", "value": ["paid"], "operator": "exact", "type": "event"}],
                1,
                range(20, 21),
            ),
        ]
    )
    def test_reads_a_sample_of_an_insight_with_more_events_than_the_limit(
        self, _name: str, properties: list[dict[str, Any]], sample_rate: float, events_checked: range
    ) -> None:
        for person in range(200):
            self._events(
                2,
                distinct_id=f"person-{person}",
                event=WIDELY_SENT_EVENT,
                properties={"plan": "paid"} if person < 10 else None,
            )
        flush_persons_and_events()

        with (
            patch(f"{CHECKS_MODULE}.MAX_CHECKED_EVENTS", 100),
            patch(f"{CHECKS_MODULE}.MIN_SAMPLED_EVENTS", 40),
            patch(f"{CHECKS_MODULE}.RESAMPLED_EVENTS", 100),
        ):
            result = self._check(
                self._query(series={"kind": "EventsNode", "event": WIDELY_SENT_EVENT}, properties=properties)
            )

        assert result["sample_rate"] == sample_rate
        assert result["events_checked"] in events_checked

    @parameterized.expand(
        [
            ("unknown_event", {"kind": "EventsNode", "event": "never sent"}, "no_events"),
            ("action_series", {"kind": "ActionsNode", "id": 1}, "unsupported"),
        ]
    )
    def test_reports_why_nothing_was_checked(self, _name: str, series: dict[str, Any], expected: str) -> None:
        result = self._check(self._query(series=series))

        assert result["status"] == expected
        assert {check["level"] for check in result["checks"]} == {"skipped"}

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
        assert {key: response.json()[key] for key in expected} == expected

    def test_does_not_check_an_insight_from_another_project(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        insight = Insight.objects.create(team=other_team, query=self._query())

        response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight.id}/data_checks/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_hides_a_property_the_member_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        self._events(40, event=WIDELY_SENT_EVENT, properties={"plan": "paid"})
        flush_persons_and_events()
        query = self._query(
            series={"kind": "EventsNode", "event": WIDELY_SENT_EVENT},
            properties=[{"key": "plan", "value": ["paid"], "operator": "exact", "type": "event"}],
        )
        assert self._check(query)["events_checked"] == 40

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

        assert self._check(query)["status"] == "no_events"

    @parameterized.expand(
        [
            ("without_a_query", None),
            ("with_a_filter_that_is_not_valid_sql", {"properties": [{"type": "hogql", "key": "1 +"}]}),
        ]
    )
    def test_rejects_a_request_it_cannot_check(self, _name: str, source: dict[str, Any] | None) -> None:
        body = {} if source is None else {"query": self._query(**source)}

        response = self.client.post(f"/api/projects/{self.team.id}/insights/data_checks/", body, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
