from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.growth.backend.constants import TEAM_SDK_CACHE_EXPIRY
from products.growth.backend.team_sdk_versions import get_and_cache_team_sdk_versions, get_sdk_versions_for_team


class TestGetSdkVersionsForTeam(SimpleTestCase):
    @patch("products.growth.backend.team_sdk_versions.run_query")
    @patch("products.growth.backend.team_sdk_versions.Team.objects.get")
    def test_sorts_partial_and_full_semver_versions_consistently(
        self, mock_team_get: MagicMock, mock_run_query: MagicMock
    ) -> None:
        mock_team_get.return_value = MagicMock()
        mock_run_query.return_value = MagicMock(
            results=[
                ("posthog-server", "1.2.0", "2026-07-14T00:00:00Z", 100),
                ("posthog-server", "1.10", "2026-07-14T00:00:00Z", 50),
            ]
        )

        result = get_sdk_versions_for_team(team_id=1)

        assert result is not None
        assert [entry["lib_version"] for entry in result["posthog-server"]] == ["1.10", "1.2.0"]


class TestGetAndCacheTeamSdkVersions(SimpleTestCase):
    @patch("products.growth.backend.team_sdk_versions.get_sdk_versions_for_team")
    def test_uses_team_sdk_cache_expiry(self, mock_get_sdk_versions: MagicMock):
        mock_get_sdk_versions.return_value = {"web": [{"lib_version": "1.0.0", "max_timestamp": "x", "count": 1}]}
        mock_redis = MagicMock()

        get_and_cache_team_sdk_versions(team_id=1, redis_client=mock_redis)

        mock_redis.setex.assert_called_once()
        key, ttl, _payload = mock_redis.setex.call_args[0]
        assert key == "sdk_versions:team:v2:1"
        assert ttl == TEAM_SDK_CACHE_EXPIRY
