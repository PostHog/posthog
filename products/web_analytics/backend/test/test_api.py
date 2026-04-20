from datetime import timedelta
from urllib.parse import urlparse

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils import timezone

from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.utils import uuid7

QUERY_TIMESTAMP = "2025-01-29"


def _create_pageview(team, distinct_id="user_1", session_id=None, url=None, timestamp=None):
    props: dict = {"$session_id": session_id or str(uuid7(timestamp or "2025-01-25"))}
    if url:
        props["$current_url"] = url
        props["$pathname"] = urlparse(url).path or url
    _create_event(
        team=team,
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=timestamp or (timezone.now() - timedelta(days=1)).isoformat(),
        properties=props,
    )


class TestWebAnalyticsDigestAPI(ClickhouseTestMixin, APIBaseTest):
    def test_returns_digest_shape(self):
        with freeze_time(QUERY_TIMESTAMP):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            _create_pageview(self.team, distinct_id="user_1", url="https://example.com/", timestamp="2025-01-25")
            flush_persons_and_events()

            response = self.client.get(f"/api/environments/{self.team.id}/web_analytics/weekly_digest/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert set(data.keys()) == {
            "visitors",
            "pageviews",
            "sessions",
            "bounce_rate",
            "avg_session_duration",
            "top_pages",
            "top_sources",
            "goals",
            "dashboard_url",
        }
        assert set(data["visitors"].keys()) == {"current", "previous", "change"}
        assert isinstance(data["top_pages"], list)
        assert isinstance(data["top_sources"], list)
        assert isinstance(data["goals"], list)
        assert "/web" in data["dashboard_url"]

    def test_empty_team_returns_zero_metrics(self):
        with freeze_time(QUERY_TIMESTAMP):
            response = self.client.get(f"/api/environments/{self.team.id}/web_analytics/weekly_digest/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["visitors"]["current"] == 0
        assert data["pageviews"]["current"] == 0
        assert data["top_pages"] == []
        assert data["top_sources"] == []
        assert data["goals"] == []

    def test_cannot_read_other_teams_digest(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        response = self.client.get(f"/api/environments/{other_team.id}/web_analytics/weekly_digest/")

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)
