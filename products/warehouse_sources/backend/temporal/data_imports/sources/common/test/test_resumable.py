import pytest
from unittest.mock import MagicMock, patch

import redis.exceptions as redis_exceptions

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class _SweepPosition:
    cursor: str | None = None


def _manager() -> ResumableSourceManager[_SweepPosition]:
    return ResumableSourceManager[_SweepPosition](MagicMock(team_id=1, job_id="job-1"), _SweepPosition)


class TestResumableSourceManager:
    def test_state_written_by_a_newer_deploy_still_loads(self):
        manager = _manager()
        redis = MagicMock()
        redis.get.return_value = '{"cursor": "cus_1", "nested_starting_after": "txn_9"}'

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            state = manager.load_state()

        assert state == _SweepPosition(cursor="cus_1")

    def test_state_reaches_redis_only_on_commit(self):
        manager = _manager()
        redis = MagicMock()

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.save_state(_SweepPosition(cursor="cus_1"))
            manager.save_state(_SweepPosition(cursor="cus_2"))
            redis.set.assert_not_called()

            manager.commit()
            manager.commit()

        redis.set.assert_called_once_with(
            "posthog:data_warehouse:resumable_source:1:job-1", '{"cursor":"cus_2"}', ex=60 * 60 * 24
        )

    def test_commit_persists_what_a_namespaced_sibling_staged(self):
        manager = _manager()
        redis = MagicMock()

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.with_namespace("deltas").save_state(_SweepPosition(cursor="cus_3"))
            manager.commit()

        redis.set.assert_called_once_with(
            "posthog:data_warehouse:resumable_source:1:job-1:deltas", '{"cursor":"cus_3"}', ex=60 * 60 * 24
        )

    def test_clear_state_drops_the_staged_cursor(self):
        manager = _manager()
        redis = MagicMock()

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.save_state(_SweepPosition(cursor="cus_1"))
            manager.clear_state()
            manager.commit()

        redis.delete.assert_called_once_with("posthog:data_warehouse:resumable_source:1:job-1")
        redis.set.assert_not_called()

    def test_commit_retries_once_after_a_stale_replica_write(self):
        manager = _manager()
        redis = MagicMock()
        redis.set.side_effect = [
            redis_exceptions.ReadOnlyError("You can't write against a read only replica."),
            None,
        ]

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.save_state(_SweepPosition(cursor="cus_1"))
            manager.commit()

        redis.connection_pool.disconnect.assert_called_once()
        assert redis.set.call_count == 2

    def test_clear_state_retries_once_after_a_stale_replica_write(self):
        manager = _manager()
        redis = MagicMock()
        redis.delete.side_effect = [
            redis_exceptions.ReadOnlyError("You can't write against a read only replica."),
            None,
        ]

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.clear_state()

        redis.connection_pool.disconnect.assert_called_once()
        assert redis.delete.call_count == 2

    def test_clear_state_raises_when_the_retry_also_hits_a_stale_replica(self):
        manager = _manager()
        redis = MagicMock()
        redis.delete.side_effect = redis_exceptions.ReadOnlyError("You can't write against a read only replica.")

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            with pytest.raises(redis_exceptions.ReadOnlyError):
                manager.clear_state()

        redis.connection_pool.disconnect.assert_called_once()
        assert redis.delete.call_count == 2
