from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.growth.backend.constants import TEAM_SDK_CACHE_EXPIRY
from products.growth.backend.team_sdk_versions import get_and_cache_team_sdk_versions


class TestGetAndCacheTeamSdkVersions(TestCase):
    @patch("products.growth.backend.team_sdk_versions.get_sdk_versions_for_team")
    def test_uses_team_sdk_cache_expiry(self, mock_get_sdk_versions: MagicMock):
        mock_get_sdk_versions.return_value = {"web": [{"lib_version": "1.0.0", "max_timestamp": "x", "count": 1}]}
        mock_redis = MagicMock()

        get_and_cache_team_sdk_versions(team_id=1, redis_client=mock_redis)

        mock_redis.setex.assert_called_once()
        _key, ttl, _payload = mock_redis.setex.call_args[0]
        assert ttl == TEAM_SDK_CACHE_EXPIRY
