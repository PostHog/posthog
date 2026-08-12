import dataclasses

from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable"


@dataclasses.dataclass(frozen=True)
class _Cursor:
    cursor: str


def _inputs(reset_pipeline: bool) -> SourceInputs:
    return SourceInputs(
        schema_name="subscriptions",
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=reset_pipeline,
    )


class TestResumableSourceManagerReset:
    def test_reset_run_never_resumes_or_checkpoints_without_touching_redis(self) -> None:
        # A reset (resync) wipes the table and re-pulls everything; resuming from a mid-stream cursor
        # would stitch a partial interrupted attempt onto the resumed remainder and finalize as
        # Completed with fewer rows than the source holds. Guard every entry point, short-circuiting
        # before Redis so a reset attempt always restarts cleanly.
        manager: ResumableSourceManager[_Cursor] = ResumableSourceManager(_inputs(reset_pipeline=True), _Cursor)

        with patch(f"{_MODULE}.get_client") as get_client:
            assert manager.can_resume() is False
            assert manager.load_state() is None
            manager.save_state(_Cursor(cursor="page-2"))

            get_client.assert_not_called()

    def test_normal_run_still_consults_and_writes_redis(self) -> None:
        # Wiring guard: the reset short-circuit must not disable resume for ordinary runs.
        manager: ResumableSourceManager[_Cursor] = ResumableSourceManager(_inputs(reset_pipeline=False), _Cursor)

        redis = MagicMock()
        redis.exists.return_value = 1
        with patch(f"{_MODULE}.get_client", return_value=redis):
            assert manager.can_resume() is True

            manager.save_state(_Cursor(cursor="page-2"))
            redis.set.assert_called_once()
