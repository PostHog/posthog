from unittest.mock import MagicMock, patch

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
