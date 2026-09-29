import typing

import pytest
from unittest.mock import MagicMock, patch

import redis.exceptions as redis_exceptions

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import (
    ResumableSourceManager,
    resolve_resume_manager,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.keyset import KeysetResumeState
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.types import ExternalDataSourceType


@frozen
class _SweepPosition:
    cursor: str | None = None


def _manager() -> ResumableSourceManager[_SweepPosition]:
    return ResumableSourceManager[_SweepPosition](MagicMock(team_id=1, job_id="job-1"), _SweepPosition)


class TestResolveResumeManager:
    """The choke point every caller reads: a class that *can* resume, ANDed with a run that can."""

    def test_a_run_that_cannot_resume_resolves_to_no_manager(self):
        # The case that matters: a resumable source class whose current table isn't seekable. Callers
        # treat a manager as "this run commits a cursor", so leaving it set here would have the
        # pipeline suppress its table reset and stop coalescing for a run that checkpoints nothing.
        resource = SourceResponse(name="t", items=lambda: iter(()), primary_keys=None, supports_resume=False)

        assert resolve_resume_manager(_manager(), resource) is None

    def test_a_resumable_run_keeps_its_manager(self):
        manager = _manager()
        resource = SourceResponse(name="t", items=lambda: iter(()), primary_keys=None, supports_resume=True)

        assert resolve_resume_manager(manager, resource) is manager

    def test_a_source_without_a_manager_stays_without_one(self):
        resource = SourceResponse(name="t", items=lambda: iter(()), primary_keys=None, supports_resume=True)

        assert resolve_resume_manager(None, resource) is None


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

    def test_committing_persists_the_staged_state_even_when_the_block_raises(self):
        manager = _manager()
        redis = MagicMock()

        with patch.object(ResumableSourceManager, "_get_redis") as get_redis:
            get_redis.return_value.__enter__.return_value = redis
            with pytest.raises(RuntimeError):
                with manager.committing():
                    manager.save_state(_SweepPosition(cursor="job_1"))
                    raise RuntimeError("export failed")

        redis.set.assert_called_once_with(
            "posthog:data_warehouse:resumable_source:1:job-1", '{"cursor":"job_1"}', ex=60 * 60 * 24
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


class TestResumeCoversRun:
    @staticmethod
    def _resume_state_of(source) -> type | None:
        """The state class a source checkpoints, read off its `ResumableSource[...]` base."""
        for base in getattr(type(source), "__orig_bases__", ()):
            if typing.get_origin(base) is ResumableSource:
                args = typing.get_args(base)
                if len(args) > 1:
                    return args[1]
        return None

    def test_a_keyset_source_never_claims_the_resumable_budget_for_an_incremental_run(self):
        # Keyset seeking is a full-load path, so a keyset source's incremental runs resume from the
        # watermark like any other source's do. Covering them here hands every one the resumable
        # retry allowance — for the Postgres family that is most of the fleet, and the runs that
        # cannot resume redo the whole read on each of those extra attempts. Derived from the state
        # class so the next source to adopt `KeysetResumeState` is held to the same rule. Snowflake
        # is deliberately not caught: it checkpoints on the incremental field, so its resume does
        # cover incremental runs.
        keyset_sources: list[ResumableSource] = [
            source
            for source in SourceRegistry.get_all_sources().values()
            if isinstance(source, ResumableSource) and self._resume_state_of(source) is KeysetResumeState
        ]
        assert keyset_sources, "expected at least one source to checkpoint with KeysetResumeState"

        covered = [
            source.source_type
            for source in keyset_sources
            if source.resume_covers_run(incremental_or_append=True, keyset_full_load_enabled=True)
        ]
        assert covered == []

    def test_a_full_load_the_flag_has_not_reached_is_not_covered(self):
        # A full load only resumes once the flag turns seeking on for it. Covering it before then
        # hands the resumable allowance to a run that still restarts, so each extra attempt redoes
        # the whole read.
        postgres = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
        assert isinstance(postgres, ResumableSource)

        assert postgres.resume_covers_run(incremental_or_append=False, keyset_full_load_enabled=False) is False
        assert postgres.resume_covers_run(incremental_or_append=False, keyset_full_load_enabled=True) is True

    def test_the_default_covers_every_run_of_any_other_resumable_source(self):
        # A REST source paginates the same way whichever sync type it runs, and Snowflake checkpoints
        # on its incremental field, so narrowing the default would cut their retry budgets.
        for incremental in (True, False):
            assert ResumableSource.resume_covers_run(MagicMock(), incremental_or_append=incremental) is True
