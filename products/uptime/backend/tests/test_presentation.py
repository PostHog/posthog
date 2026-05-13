from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from rest_framework import status

from products.uptime.backend.models import Monitor
from products.uptime.backend.tests.conftest import UptimeTeamScopedTestMixin

NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))


class TestSuggestedUrlsEndpoint(UptimeTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/uptime/monitors/suggested_urls/"

    def test_returns_ranked_suggestions(self) -> None:
        _create_person(distinct_ids=["u1"], team=self.team)
        with freeze_time(NOW):
            for _ in range(3):
                _create_event(
                    team=self.team,
                    distinct_id="u1",
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com/", "$host": "posthog.com", "$pathname": "/"},
                )
            _create_event(
                team=self.team,
                distinct_id="u1",
                event="$pageview",
                properties={"$current_url": "https://github.com/", "$host": "github.com", "$pathname": "/"},
            )

            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [r["host"] for r in data] == ["posthog.com", "github.com"]
        assert data[0]["url"] == "https://posthog.com"
        assert data[0]["event_count"] == 3

    def test_excludes_already_monitored(self) -> None:
        Monitor.objects.create(team_id=self.team.id, name="ph", url="https://posthog.com")
        _create_person(distinct_ids=["u1"], team=self.team)
        with freeze_time(NOW):
            _create_event(
                team=self.team,
                distinct_id="u1",
                event="$pageview",
                properties={"$current_url": "https://posthog.com/", "$host": "posthog.com", "$pathname": "/"},
            )
            _create_event(
                team=self.team,
                distinct_id="u1",
                event="$pageview",
                properties={"$current_url": "https://github.com/", "$host": "github.com", "$pathname": "/"},
            )

            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert [r["host"] for r in response.json()] == ["github.com"]


class TestBulkCreateEndpoint(UptimeTeamScopedTestMixin, APIBaseTest):
    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/uptime/monitors/bulk_create/"

    def test_creates_multiple_monitors(self) -> None:
        response = self.client.post(
            self._url(),
            data={
                "monitors": [
                    {"name": "PostHog", "url": "https://posthog.com"},
                    {"name": "GitHub", "url": "https://github.com"},
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        created = response.json()
        assert len(created) == 2
        assert {m["url"] for m in created} == {"https://posthog.com", "https://github.com"}
        assert Monitor.objects.filter(team_id=self.team.id).count() == 2

    def test_rejects_empty_list(self) -> None:
        response = self.client.post(self._url(), data={"monitors": []}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Monitor.objects.filter(team_id=self.team.id).count() == 0

    def test_rejects_invalid_url(self) -> None:
        response = self.client.post(
            self._url(),
            data={"monitors": [{"name": "bad", "url": "not-a-url"}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Monitor.objects.filter(team_id=self.team.id).count() == 0
