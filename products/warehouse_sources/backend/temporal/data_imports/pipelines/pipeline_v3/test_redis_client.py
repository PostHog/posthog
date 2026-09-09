import pytest
from unittest.mock import MagicMock, patch

import redis

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import redis_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.redis_client import get_redis_client

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.redis_client"


@pytest.fixture(autouse=True)
def _clear_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_client, "_cooldown_until", 0.0)


class TestGetRedisClient:
    @patch(f"{_MODULE}.get_client")
    def test_recovers_from_transient_connection_error(self, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = [redis.exceptions.ConnectionError("Temporary failure in name resolution"), None]
        mock_get_client.return_value = mock_redis

        with get_redis_client() as client:
            assert client is mock_redis
        assert mock_redis.ping.call_count == 2

    @patch(f"{_MODULE}.capture_exception")
    @patch(f"{_MODULE}.get_client")
    def test_fails_closed_after_retries_then_holds_the_fallback(
        self, mock_get_client: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = redis.exceptions.TimeoutError("Timeout connecting to server")
        mock_get_client.return_value = mock_redis

        for _ in range(3):
            with get_redis_client() as client:
                assert client is None

        assert mock_redis.ping.call_count == 3
        assert mock_capture.call_count == 1

    @patch(f"{_MODULE}.get_client")
    def test_reconnects_once_the_cooldown_expires(
        self, mock_get_client: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(redis_client, "CONNECT_FAILURE_COOLDOWN_SECONDS", 0.0)
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = [redis.exceptions.TimeoutError("Timeout connecting to server")] * 3 + [None]
        mock_get_client.return_value = mock_redis

        with get_redis_client() as client:
            assert client is None
        with get_redis_client() as client:
            assert client is mock_redis
