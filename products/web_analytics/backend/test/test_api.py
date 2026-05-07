from datetime import timedelta
from urllib.parse import urlparse

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.utils import uuid7

QUERY_TIMESTAMP = "2025-01-29"


def _create_pageview(
    team,
    distinct_id="user_1",
    session_id=None,
    url=None,
    timestamp=None,
    referring_domain=None,
):
    props: dict = {"$session_id": session_id or str(uuid7(timestamp or "2025-01-25"))}
    if url:
        props["$current_url"] = url
        props["$pathname"] = urlparse(url).path or url
    if referring_domain:
        props["$referring_domain"] = referring_domain
    _create_event(
        team=team,
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=timestamp or (timezone.now() - timedelta(days=1)).isoformat(),
        properties=props,
    )


class TestWebAnalyticsDigestAPI(ClickhouseTestMixin, APIBaseTest):
    ENDPOINT = "/api/environments/{team_id}/web_analytics/weekly_digest/"

    def _url(self, team_id=None):
        return self.ENDPOINT.format(team_id=team_id or self.team.id)

    def test_returns_digest_shape(self):
        with freeze_time(QUERY_TIMESTAMP):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            _create_pageview(self.team, distinct_id="user_1", url="https://example.com/", timestamp="2025-01-25")
            flush_persons_and_events()

            response = self.client.get(self._url())

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
            response = self.client.get(self._url())

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

        response = self.client.get(self._url(team_id=other_team.id))

        assert response.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    def test_days_param_respected(self):
        with freeze_time(QUERY_TIMESTAMP):
            _create_person(team_id=self.team.pk, distinct_ids=["user_recent"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_old"])
            _create_pageview(
                self.team,
                distinct_id="user_recent",
                url="https://example.com/recent",
                timestamp="2025-01-27T12:00:00Z",
            )
            _create_pageview(
                self.team,
                distinct_id="user_old",
                url="https://example.com/old",
                timestamp="2025-01-09T12:00:00Z",
            )
            flush_persons_and_events()

            response_7 = self.client.get(self._url(), data={"days": 7})
            response_30 = self.client.get(self._url(), data={"days": 30})

        assert response_7.status_code == status.HTTP_200_OK
        assert response_30.status_code == status.HTTP_200_OK
        assert response_7.json()["visitors"]["current"] == 1
        assert response_30.json()["visitors"]["current"] == 2

    @parameterized.expand(
        [
            ("zero", "0", status.HTTP_400_BAD_REQUEST),
            ("above_max", "91", status.HTTP_400_BAD_REQUEST),
            ("not_an_int", "abc", status.HTTP_400_BAD_REQUEST),
            ("min", "1", status.HTTP_200_OK),
            ("default_ok", "7", status.HTTP_200_OK),
            ("max", "90", status.HTTP_200_OK),
        ]
    )
    def test_days_param_validation(self, _name, days_value, expected_status):
        with freeze_time(QUERY_TIMESTAMP):
            response = self.client.get(self._url(), data={"days": days_value})

        assert response.status_code == expected_status

    def test_compare_false_omits_change(self):
        with freeze_time(QUERY_TIMESTAMP):
            _create_person(team_id=self.team.pk, distinct_ids=["user_current"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_prior"])
            _create_pageview(
                self.team,
                distinct_id="user_current",
                url="https://example.com/a",
                timestamp="2025-01-27T12:00:00Z",
            )
            _create_pageview(
                self.team,
                distinct_id="user_prior",
                url="https://example.com/b",
                timestamp="2025-01-18T12:00:00Z",
            )
            flush_persons_and_events()

            response = self.client.get(self._url(), data={"compare": "false"})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        for metric in ("visitors", "pageviews", "sessions", "bounce_rate", "avg_session_duration"):
            assert data[metric]["previous"] is None, metric
            assert data[metric]["change"] is None, metric

    def test_compare_true_populates_change_when_prior_period_has_data(self):
        with freeze_time(QUERY_TIMESTAMP):
            _create_person(team_id=self.team.pk, distinct_ids=["cur_1"])
            _create_person(team_id=self.team.pk, distinct_ids=["cur_2"])
            _create_person(team_id=self.team.pk, distinct_ids=["cur_3"])
            _create_person(team_id=self.team.pk, distinct_ids=["prev_1"])
            for distinct_id in ("cur_1", "cur_2", "cur_3"):
                _create_pageview(
                    self.team,
                    distinct_id=distinct_id,
                    url=f"https://example.com/{distinct_id}",
                    timestamp="2025-01-27T12:00:00Z",
                )
            _create_pageview(
                self.team,
                distinct_id="prev_1",
                url="https://example.com/prev",
                timestamp="2025-01-18T12:00:00Z",
            )
            flush_persons_and_events()

            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        visitors = response.json()["visitors"]
        assert visitors["current"] == 3
        assert visitors["previous"] == 1
        assert visitors["change"] is not None
        assert visitors["change"]["direction"] == "Up"
        assert visitors["change"]["percent"] == 200

    def test_top_pages_limited_to_five(self):
        with freeze_time(QUERY_TIMESTAMP):
            for idx in range(7):
                distinct_id = f"page_user_{idx}"
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                _create_pageview(
                    self.team,
                    distinct_id=distinct_id,
                    url=f"https://example.com/page-{idx}",
                    timestamp="2025-01-27T12:00:00Z",
                )
            flush_persons_and_events()

            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        top_pages = response.json()["top_pages"]
        assert len(top_pages) == 5
        for entry in top_pages:
            assert "path" in entry
            assert "visitors" in entry
            assert isinstance(entry["visitors"], int)

    def test_top_sources_limited_to_five(self):
        with freeze_time(QUERY_TIMESTAMP):
            for idx in range(7):
                distinct_id = f"src_user_{idx}"
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                _create_pageview(
                    self.team,
                    distinct_id=distinct_id,
                    url="https://example.com/landing",
                    timestamp="2025-01-27T12:00:00Z",
                    referring_domain=f"source-{idx}.example.com",
                )
            flush_persons_and_events()

            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        top_sources = response.json()["top_sources"]
        assert len(top_sources) == 5
        assert len({entry["name"] for entry in top_sources}) == 5
        for entry in top_sources:
            assert "name" in entry
            assert "visitors" in entry
            assert isinstance(entry["visitors"], int)

    def test_goals_empty_when_team_has_no_actions(self):
        with freeze_time(QUERY_TIMESTAMP):
            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["goals"] == []

    def test_unauthenticated_request_rejected(self):
        self.client.logout()

        response = self.client.get(self._url())

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            (["feature_flag:read"], status.HTTP_403_FORBIDDEN),
            (["web_analytics:read"], status.HTTP_200_OK),
            (["web_analytics:write"], status.HTTP_200_OK),
        ]
    )
    def test_personal_api_key_requires_web_analytics_read_scope(self, scopes, expected_status):
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()

        with freeze_time(QUERY_TIMESTAMP):
            response = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {api_key}")

        assert response.status_code == expected_status

    def test_dashboard_url_uses_team_id_and_utm(self):
        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        dashboard_url = response.json()["dashboard_url"]
        assert f"/project/{self.team.id}/web" in dashboard_url
        assert "utm_source=" in dashboard_url
