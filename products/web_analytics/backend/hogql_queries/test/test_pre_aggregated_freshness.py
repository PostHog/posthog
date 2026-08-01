from datetime import UTC, datetime

from unittest import TestCase
from unittest.mock import MagicMock, patch

from products.web_analytics.backend.hogql_queries.pre_aggregated.freshness import get_pre_aggregated_watermark


class TestGetPreAggregatedWatermark(TestCase):
    def setUp(self):
        redis_patcher = patch("products.web_analytics.backend.hogql_queries.pre_aggregated.freshness.redis")
        self.mock_redis = redis_patcher.start()
        self.addCleanup(redis_patcher.stop)
        self.mock_redis_client = MagicMock()
        self.mock_redis.get_client.return_value = self.mock_redis_client
        self.mock_redis_client.get.return_value = None

        sync_execute_patcher = patch(
            "products.web_analytics.backend.hogql_queries.pre_aggregated.freshness.sync_execute"
        )
        self.mock_sync_execute = sync_execute_patcher.start()
        self.addCleanup(sync_execute_patcher.stop)

    def test_returns_watermark_from_clickhouse_and_caches_it(self):
        max_bucket = datetime(2026, 8, 1, 10, 0, 0)  # naive, as clickhouse-driver returns DateTime columns
        self.mock_sync_execute.return_value = [(max_bucket,)]

        result = get_pre_aggregated_watermark(team_id=1)

        assert result == datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
        self.mock_redis_client.set.assert_called_once()
        cache_key, cached_value = self.mock_redis_client.set.call_args[0]
        assert cache_key.endswith(":1")
        assert cached_value == result.isoformat()

    def test_returns_none_when_team_has_no_preaggregated_data(self):
        self.mock_sync_execute.return_value = [(None,)]

        result = get_pre_aggregated_watermark(team_id=1)

        assert result is None
        self.mock_redis_client.set.assert_not_called()

    def test_returns_none_instead_of_raising_when_clickhouse_errors(self):
        # A team whose current-day partition build is failing shouldn't turn into a 500 on every
        # web analytics query - it should read as "freshness unknown" so the caller falls back to live.
        self.mock_sync_execute.side_effect = Exception("clickhouse is down")

        result = get_pre_aggregated_watermark(team_id=1)

        assert result is None

    def test_reads_cached_watermark_without_hitting_clickhouse(self):
        cached_iso = datetime(2026, 8, 1, 9, 30, 0, tzinfo=UTC).isoformat()
        self.mock_redis_client.get.return_value = cached_iso.encode()

        result = get_pre_aggregated_watermark(team_id=1)

        assert result == datetime(2026, 8, 1, 9, 30, 0, tzinfo=UTC)
        self.mock_sync_execute.assert_not_called()

    def test_falls_through_to_clickhouse_when_redis_read_fails(self):
        self.mock_redis_client.get.side_effect = Exception("redis is down")
        max_bucket = datetime(2026, 8, 1, 10, 0, 0)
        self.mock_sync_execute.return_value = [(max_bucket,)]

        result = get_pre_aggregated_watermark(team_id=1)

        assert result == datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
