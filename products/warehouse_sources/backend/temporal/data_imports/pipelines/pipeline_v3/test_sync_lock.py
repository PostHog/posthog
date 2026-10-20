from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

import redis
import fakeredis
import temporalio.exceptions

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    LOCK_TTL_SECONDS,
    LockAcquireResult,
    _get_redis_client,
    _lock_key,
    _lock_meta_key,
    acquire_v3_pipeline_lock,
    get_v3_pipeline_lock_holder,
    queue_attempt_token,
    release_v3_pipeline_lock,
    try_acquire_v3_pipeline_lock,
)

SYNC_LOCK = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock"


class TestLockKey:
    def test_format(self) -> None:
        assert _lock_key(1, "schema-abc") == "v3_pipeline_lock:1:schema-abc"


class TestAcquireV3PipelineLock:
    @pytest.mark.parametrize(
        "redis_up, set_effect, expected",
        [
            (True, True, LockAcquireResult.ACQUIRED),
            (True, None, LockAcquireResult.HELD),
            (True, Exception("connection lost"), LockAcquireResult.UNAVAILABLE),
            (False, None, LockAcquireResult.UNAVAILABLE),
        ],
        ids=["acquired", "already_held", "set_error", "redis_down"],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_acquire_result(
        self, mock_ctx: MagicMock, redis_up: bool, set_effect: object, expected: LockAcquireResult
    ) -> None:
        mock_redis = MagicMock()
        if isinstance(set_effect, Exception):
            mock_redis.set.side_effect = set_effect
        else:
            mock_redis.set.return_value = set_effect
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis if redis_up else None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert try_acquire_v3_pipeline_lock(1, "s-1", "tok-1") == expected
        assert acquire_v3_pipeline_lock(1, "s-1", "tok-1") is (expected == LockAcquireResult.ACQUIRED)
        if redis_up:
            mock_redis.set.assert_called_with(_lock_key(1, "s-1"), "tok-1", nx=True, ex=LOCK_TTL_SECONDS)

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_fail_closed_on_redis_unavailable(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert acquire_v3_pipeline_lock(1, "s-1", "tok-1") is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_fail_closed_on_set_exception(self, mock_ctx: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.set.side_effect = Exception("connection lost")
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert acquire_v3_pipeline_lock(1, "s-1", "tok-1") is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.capture_exception")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_propagates_activity_cancellation_instead_of_failing_closed(
        self, mock_ctx: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.set.side_effect = temporalio.exceptions.CancelledError()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(temporalio.exceptions.CancelledError):
            acquire_v3_pipeline_lock(1, "s-1", "tok-1")
        mock_capture.assert_not_called()


class TestGetV3PipelineLockHolder:
    @pytest.mark.parametrize(
        "get_return, expected",
        [
            (b"tok-1", "tok-1"),
            ("tok-1", "tok-1"),
            (None, None),
        ],
        ids=["bytes_token", "str_token", "unheld"],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_holder_result(self, mock_ctx: MagicMock, get_return: bytes | str | None, expected: str | None) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = get_return
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert get_v3_pipeline_lock_holder(1, "s-1") == expected

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_none_on_redis_unavailable(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert get_v3_pipeline_lock_holder(1, "s-1") is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_none_on_get_exception(self, mock_ctx: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("connection lost")
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert get_v3_pipeline_lock_holder(1, "s-1") is None


class TestReleaseV3PipelineLock:
    @pytest.mark.parametrize(
        "holder, release_token, released",
        [
            ("tok-1", "tok-1", True),
            ("tok-1", "tok-2", False),
            (queue_attempt_token("job-1", 2), queue_attempt_token("job-1", 2), True),
            # The loader and the teardown paths release a queue run by its job id.
            (queue_attempt_token("job-1", 2), "job-1", True),
            # A stuck earlier attempt must never release the lock of the attempt that replaced it.
            (queue_attempt_token("job-1", 3), queue_attempt_token("job-1", 2), False),
            (queue_attempt_token("job-10", 1), "job-1", False),
            ("job-1", queue_attempt_token("job-1", 1), False),
        ],
        ids=[
            "same_token",
            "other_token",
            "same_attempt",
            "queue_job_id_releases_its_attempt",
            "earlier_attempt_cannot_release_later_one",
            "job_id_prefix_of_another_job",
            "attempt_token_cannot_release_bare_job_id",
        ],
    )
    def test_release_compares_the_token(self, holder: str, release_token: str, released: bool) -> None:
        client = fakeredis.FakeRedis()
        client.set(_lock_key(1, "s-1"), holder)
        client.set(_lock_meta_key(1, "s-1"), "{}")

        @contextmanager
        def _fake_client() -> Iterator[fakeredis.FakeRedis]:
            yield client

        with patch(f"{SYNC_LOCK}._get_redis_client", _fake_client):
            assert release_v3_pipeline_lock(1, "s-1", release_token) is released
        assert (client.get(_lock_key(1, "s-1")) is None) is released
        assert (client.get(_lock_meta_key(1, "s-1")) is None) is released

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_false_on_redis_unavailable(self, mock_ctx: MagicMock) -> None:
        mock_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert release_v3_pipeline_lock(1, "s-1", "tok-1") is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_returns_false_on_eval_exception(self, mock_ctx: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.eval.side_effect = Exception("connection lost")
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        assert release_v3_pipeline_lock(1, "s-1", "tok-1") is False

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.capture_exception")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock._get_redis_client")
    def test_propagates_activity_cancellation_instead_of_failing_silently(
        self, mock_ctx: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.eval.side_effect = temporalio.exceptions.CancelledError()
        mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_redis)
        mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with pytest.raises(temporalio.exceptions.CancelledError):
            release_v3_pipeline_lock(1, "s-1", "tok-1")
        mock_capture.assert_not_called()


class TestGetRedisClient:
    """The acquire/release activities run with a single Temporal attempt, so a bare
    DNS/connection blip previously skipped the whole scheduled sync run with no retry."""

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.get_client")
    def test_recovers_from_transient_connection_error(self, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = [redis.exceptions.ConnectionError("Temporary failure in name resolution"), None]
        mock_get_client.return_value = mock_redis

        with _get_redis_client() as client:
            assert client is mock_redis
        assert mock_redis.ping.call_count == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.get_client")
    def test_fails_closed_after_exhausting_retries(self, mock_get_client: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = redis.exceptions.ConnectionError("Temporary failure in name resolution")
        mock_get_client.return_value = mock_redis

        with _get_redis_client() as client:
            assert client is None
        assert mock_redis.ping.call_count == 3

    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.capture_exception")
    @patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock.get_client")
    def test_propagates_activity_cancellation_instead_of_failing_closed(
        self, mock_get_client: MagicMock, mock_capture: MagicMock
    ) -> None:
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = temporalio.exceptions.CancelledError()
        mock_get_client.return_value = mock_redis

        with pytest.raises(temporalio.exceptions.CancelledError):
            with _get_redis_client():
                pass
        mock_capture.assert_not_called()
