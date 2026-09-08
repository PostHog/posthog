import pytest
from unittest.mock import MagicMock, patch

from redis.exceptions import ReadOnlyError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class _SweepPosition:
    cursor: str | None = None


class TestResumableSourceManager:
    def test_state_written_by_a_newer_deploy_still_loads(self):
        manager = ResumableSourceManager[_SweepPosition](MagicMock(team_id=1, job_id="job-1"), _SweepPosition)
        redis = MagicMock()
        redis.get.return_value = '{"cursor": "cus_1", "nested_starting_after": "txn_9"}'

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            state = manager.load_state()

        assert state == _SweepPosition(cursor="cus_1")

    def test_save_state_retries_once_after_stale_connection_read_only_error(self):
        manager = ResumableSourceManager[_SweepPosition](MagicMock(team_id=1, job_id="job-1"), _SweepPosition)
        redis = MagicMock()
        redis.set.side_effect = [ReadOnlyError("You can't write against a read only replica."), None]

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            manager.save_state(_SweepPosition(cursor="cus_1"))

        assert redis.set.call_count == 2
        redis.connection_pool.disconnect.assert_called_once()

    def test_save_state_raises_when_retry_also_hits_read_only_error(self):
        manager = ResumableSourceManager[_SweepPosition](MagicMock(team_id=1, job_id="job-1"), _SweepPosition)
        redis = MagicMock()
        redis.set.side_effect = ReadOnlyError("You can't write against a read only replica.")

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            with pytest.raises(ReadOnlyError):
                manager.save_state(_SweepPosition(cursor="cus_1"))

        assert redis.set.call_count == 2
