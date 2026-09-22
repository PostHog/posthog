from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.rate_limit import FeatureFlagRequestUsageBurstRateThrottle

from products.feature_flags.backend.facade.api import FeatureFlagRequestType, FeatureFlagRequestUsage
from products.feature_flags.backend.presentation.request_usage import FeatureFlagRequestUsageQuerySerializer


class TestFeatureFlagRequestUsage(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_flag_patcher = patch(
            "products.feature_flags.backend.presentation.request_usage.feature_enabled_or_false", return_value=True
        )
        feature_flag_patcher.start()
        self.addCleanup(feature_flag_patcher.stop)

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    @parameterized.expand(
        [
            ("hour", "2026-08-01T00:00:00Z", "2026-08-09T00:00:01Z"),
            ("day", "2026-07-01T00:00:00Z", "2026-08-02T00:00:01Z"),
        ]
    )
    def test_rejects_ranges_that_exceed_the_interval_limit(self, interval: str, date_from: str, date_to: str) -> None:
        serializer = FeatureFlagRequestUsageQuerySerializer(
            data={"time_interval": interval, "date_from": date_from, "date_to": date_to}
        )

        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors

    def test_accepts_hourly_range_from_last_seven_days_preset(self) -> None:
        serializer = FeatureFlagRequestUsageQuerySerializer(
            data={
                "time_interval": "hour",
                "date_from": "2026-08-01T00:00:00Z",
                "date_to": "2026-08-08T23:59:59Z",
            }
        )

        assert serializer.is_valid(), serializer.errors

    def test_rejects_inverted_date_range(self) -> None:
        serializer = FeatureFlagRequestUsageQuerySerializer(
            data={
                "time_interval": "day",
                "date_from": "2026-08-21T00:00:00Z",
                "date_to": "2026-08-20T00:00:00Z",
            }
        )

        assert not serializer.is_valid()
        assert serializer.errors["non_field_errors"] == ["date_from must be earlier than date_to."]

    @patch("products.feature_flags.backend.presentation.request_usage.get_feature_flag_request_usage")
    def test_returns_usage_for_the_project_in_the_url(self, mock_get_usage) -> None:
        mock_get_usage.return_value = [
            FeatureFlagRequestUsage(
                bucket=datetime(2026, 8, 20, tzinfo=UTC),
                request_type=FeatureFlagRequestType.LOCAL_EVALUATION,
                sdk="posthog-ruby",
                request_count=12,
                billing_units=120,
            )
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flag_request_usage/",
            {
                "date_from": "2026-08-20T00:00:00Z",
                "date_to": "2026-08-21T00:00:00Z",
                "time_interval": "hour",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"][0] == {
            "bucket": "2026-08-20T00:00:00Z",
            "request_type": "local_evaluation",
            "sdk": "posthog-ruby",
            "request_count": 12,
            "billing_units": 120,
        }
        assert mock_get_usage.call_args.kwargs["team_id"] == self.team.id

    def test_returns_not_found_when_request_usage_flag_is_disabled(self) -> None:
        with patch(
            "products.feature_flags.backend.presentation.request_usage.feature_enabled_or_false", return_value=False
        ):
            response = self.client.get(
                f"/api/projects/{self.team.id}/feature_flag_request_usage/",
                {
                    "date_from": "2026-08-20T00:00:00Z",
                    "date_to": "2026-08-21T00:00:00Z",
                    "time_interval": "hour",
                },
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False)
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.feature_flags.backend.presentation.request_usage.get_feature_flag_request_usage", return_value=[])
    def test_session_requests_are_rate_limited(self, _mock_get_usage, _rate_limit_enabled, _team_can_bypass) -> None:
        query = {
            "date_from": "2026-08-20T00:00:00Z",
            "date_to": "2026-08-21T00:00:00Z",
            "time_interval": "hour",
        }

        with patch.object(FeatureFlagRequestUsageBurstRateThrottle, "rate", "1/minute"):
            first_response = self.client.get(f"/api/projects/{self.team.id}/feature_flag_request_usage/", query)
            second_response = self.client.get(f"/api/projects/{self.team.id}/feature_flag_request_usage/", query)

        assert first_response.status_code == status.HTTP_200_OK
        assert second_response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_request_usage_throttle_uses_one_bucket_per_project(self) -> None:
        throttle = FeatureFlagRequestUsageBurstRateThrottle()
        view = Mock(team_id=self.team.id)
        first_user_request = Mock(user=Mock(is_authenticated=True, pk=1))
        second_user_request = Mock(user=Mock(is_authenticated=True, pk=2))

        first_cache_key = throttle.get_cache_key(first_user_request, view)
        assert first_cache_key == throttle.get_cache_key(second_user_request, view)
        assert str(self.team.id) in first_cache_key
