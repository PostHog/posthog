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


class TestSummaryEndpoint(UptimeTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/uptime/monitors/summary/"

    def test_returns_summary_for_each_monitor(self) -> None:
        Monitor.objects.create(team_id=self.team.id, name="a", url="https://a.io")
        Monitor.objects.create(team_id=self.team.id, name="b", url="https://b.io")

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        assert {row["name"] for row in data} == {"a", "b"}
        for row in data:
            assert row["status"] == "no_data"
            assert len(row["daily_buckets"]) == 90
            assert row["uptime_90d"] is None


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


class TestMonitorModeEndpoints(UptimeTeamScopedTestMixin, APIBaseTest):
    def _list_url(self) -> str:
        return f"/api/environments/{self.team.id}/uptime/monitors/"

    def _ping_now_url(self, monitor_id) -> str:
        return f"/api/environments/{self.team.id}/uptime/monitors/{monitor_id}/ping_now/"

    def test_create_auto_requires_url(self) -> None:
        response = self.client.post(
            self._list_url(),
            data={"name": "no-url", "mode": "auto"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_manual_url_is_optional(self) -> None:
        response = self.client.post(
            self._list_url(),
            data={"name": "Payments", "mode": "manual"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["mode"] == "manual"
        assert body["url"] is None

    def test_create_manual_with_url_still_works(self) -> None:
        response = self.client.post(
            self._list_url(),
            data={"name": "Payments", "url": "https://stripe.com", "mode": "manual"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["url"] == "https://stripe.com"

    def test_ping_now_rejects_manual_monitor(self) -> None:
        monitor = Monitor.objects.create(team_id=self.team.id, name="manual-only", url=None, mode="manual")

        response = self.client.post(self._ping_now_url(monitor.id))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        # DRF ValidationError on a dict comes back as { attr: "mode", code: "invalid_input", ... }
        assert body.get("attr") == "mode"
