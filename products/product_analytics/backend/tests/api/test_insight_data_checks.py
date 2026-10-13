from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.team import Team

from products.product_analytics.backend.facade.models import Insight

NOW = datetime(2026, 3, 10, 12, tzinfo=UTC)
EVENT = "signed up"
WIDELY_SENT_EVENT = "opened app"
BOT_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
LOCAL_HOST = "localhost:8010"


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
        self._events(60, properties={"$raw_user_agent": BOT_USER_AGENT})
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

    def _query(self, series: dict[str, Any] | None = None, **source: Any) -> dict[str, Any]:
        return {
            "kind": "InsightVizNode",
            "source": {
                # Not a trends query: the repo's crossing scan reads one in a test as a run of web analytics code.
                "kind": "LifecycleQuery",
                "series": [series or {"kind": "EventsNode", "event": EVENT}],
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
            (
                "property_filter",
                {"properties": [{"key": "$host", "value": [LOCAL_HOST], "operator": "exact", "type": "event"}]},
                60,
            ),
            ("shorter_date_range", {"dateRange": {"date_from": "-12h"}}, 0),
        ]
    )
    def test_checks_only_what_the_insights_own_filters_keep(
        self, _name: str, source: dict[str, Any], events_checked: int
    ) -> None:
        assert self._check(self._query(**source))["events_checked"] == events_checked

    def test_reads_a_sample_of_an_insight_with_more_events_than_the_limit(self) -> None:
        for person in range(200):
            self._events(2, distinct_id=f"person-{person}", event=WIDELY_SENT_EVENT)
        flush_persons_and_events()

        with patch("products.product_analytics.backend.insight_data_checks.MAX_CHECKED_EVENTS", 100):
            result = self._check(self._query(series={"kind": "EventsNode", "event": WIDELY_SENT_EVENT}))

        assert result["sample_rate"] == 0.25
        assert 0 < result["events_checked"] < 400

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

    def test_rejects_a_request_without_a_query(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/insights/data_checks/", {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
