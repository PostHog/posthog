import uuid
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake
from deltalake.exceptions import CommitFailedError, DeltaError

from posthog.models import Team

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import APPEND_RUN_MARKER_KEY, ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import PostLoadResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.append_rollback import (
    clear_append_run_marker,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    process_message,
    process_messages,
)

_PROCESSOR = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor"

_SEED_IDS = [1, 2]
_SEED_WATERMARK = 2
# The window that every run after the seed reads, because no run before it moved the watermark.
_WINDOW = [[3, 4], [5, 6], [7, 8]]
_WINDOW_IDS = [3, 4, 5, 6, 7, 8]


class _Loader:
    """Drives the load processor against a local Delta table and the test database."""

    def __init__(self, team: Team, table_path: str, sync_type: str = "append") -> None:
        self.team = team
        self.table_path = table_path
        self.sync_type = sync_type
        self.source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Postgres"
        )
        self.schema = ExternalDataSchema.objects.create(
            name="events",
            team=team,
            source=self.source,
            sync_type=sync_type,
            sync_type_config={
                "incremental_field": "id",
                "incremental_field_type": "integer",
                "incremental_field_last_value": _SEED_WATERMARK,
            },
        )
        self._batches: dict[str, pa.Table] = {}

    def seed(self) -> None:
        write_deltalake(self.table_path, pa.table({"id": _SEED_IDS}))

    def new_job(self) -> ExternalDataJob:
        return ExternalDataJob.objects.create(
            team=self.team,
            pipeline=self.source,
            schema=self.schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            billable=True,
            workflow_run_id=str(uuid.uuid4()),
        )

    def messages(
        self,
        job: ExternalDataJob,
        batches: list[list[int]],
        *,
        attempt: int = 1,
        final: bool,
        is_resume: bool = False,
    ) -> list[dict[str, Any]]:
        """Stage the watermark like the extract side does, and return the queue messages of the run."""
        run_uuid = f"{job.workflow_run_id}-a{attempt}"
        self.schema.stage_incremental_field_value(run_uuid, max(max(ids) for ids in batches))
        ExternalDataJob.objects.filter(id=job.id).update(rows_synced=sum(len(ids) for ids in batches))
        messages = []
        for index, ids in enumerate(batches):
            path = f"s3://bucket/{run_uuid}/{index}.parquet"
            self._batches[path] = pa.table({"id": ids})
            last = final and index == len(batches) - 1
            messages.append(
                {
                    "team_id": self.team.id,
                    "job_id": str(job.id),
                    "schema_id": str(self.schema.id),
                    "source_id": str(self.source.id),
                    "resource_name": "events",
                    "run_uuid": run_uuid,
                    "batch_index": index,
                    "s3_path": path,
                    "row_count": len(ids),
                    "byte_size": 1,
                    "is_final_batch": last,
                    "total_batches": len(batches) if last else None,
                    "total_rows": sum(len(b) for b in batches) if last else None,
                    "sync_type": self.sync_type,
                    "data_folder": None,
                    "schema_path": None,
                    "primary_keys": ["id"] if self.sync_type == "incremental" else None,
                    "is_resume": is_resume,
                }
            )
        return messages

    def load(self, messages: list[dict[str, Any]]) -> None:
        for message in messages:
            process_message(message)

    def fail(self, job: ExternalDataJob, error: str) -> None:
        ExternalDataJob.objects.filter(id=job.id).update(status=ExternalDataJob.Status.FAILED, latest_error=error)

    def ids(self) -> list[int]:
        ids = cast(list[int], DeltaTable(self.table_path).to_pyarrow_table().column("id").to_pylist())
        return sorted(ids)

    def config(self) -> dict[str, Any]:
        return ExternalDataSchema.objects.get(id=self.schema.id).sync_type_config

    def operations(self) -> list[str]:
        return [commit["operation"] for commit in DeltaTable(self.table_path).history()]


@pytest.fixture(autouse=True)
def _boundaries(settings: Any) -> Iterator[None]:
    settings.DATA_WAREHOUSE_APPEND_ROLLBACK_ENABLED = True
    with ExitStack() as stack:
        for target in (
            "close_old_connections",
            "posthoganalytics",
            "mark_batch_as_processed",
            "release_v3_pipeline_lock",
            "_trigger_ducklake_register_data_imports",
            "_trigger_post_import_workflow",
        ):
            stack.enter_context(patch(f"{_PROCESSOR}.{target}"))
        stack.enter_context(patch(f"{_PROCESSOR}.is_batch_already_processed", return_value=False))
        stack.enter_context(patch(f"{_PROCESSOR}.finish_row_tracking", new_callable=AsyncMock))
        stack.enter_context(
            patch(
                f"{_PROCESSOR}.run_post_load_operations",
                new_callable=AsyncMock,
                return_value=PostLoadResult(queryable_folder=None),
            )
        )
        yield


@pytest.fixture
def loader(team: Team, tmp_path: Path) -> Iterator[_Loader]:
    instance = _Loader(team, str(tmp_path / "table"))
    with ExitStack() as stack:
        stack.enter_context(
            patch(f"{_PROCESSOR}.read_parquet", side_effect=lambda path: instance._batches[path]),
        )
        stack.enter_context(
            patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=lambda **kwargs: make_local_table_ref(instance.table_path))
        )
        yield instance


def _cancelled(loader: _Loader) -> None:
    job = loader.new_job()
    loader.load(loader.messages(job, _WINDOW[:2], final=False))
    loader.fail(job, "Sync cancelled by user")


def _failed_mid_run(loader: _Loader) -> None:
    job = loader.new_job()
    loader.load(loader.messages(job, _WINDOW[:2], final=False))
    loader.fail(job, "connection to the source was lost")


def _failed_twice(loader: _Loader) -> None:
    _cancelled(loader)
    _failed_mid_run(loader)


def _failed_after_a_resumed_attempt(loader: _Loader) -> None:
    job = loader.new_job()
    loader.load(loader.messages(job, _WINDOW[:1], final=False))
    loader.load(loader.messages(job, _WINDOW[1:2], attempt=2, final=False, is_resume=True))
    loader.fail(job, "connection to the source was lost")


@pytest.mark.django_db
class TestUnfinishedAppendRun:
    @pytest.mark.parametrize(
        "unfinished_run",
        [_cancelled, _failed_mid_run, _failed_twice, _failed_after_a_resumed_attempt],
        ids=lambda case: case.__name__,
    )
    @pytest.mark.parametrize("table_exists", [True, False], ids=["existing_table", "first_sync"])
    def test_the_next_run_loads_each_row_once(self, loader: _Loader, unfinished_run: Any, table_exists: bool) -> None:
        if table_exists:
            loader.seed()

        unfinished_run(loader)
        assert loader.config()["incremental_field_last_value"] == _SEED_WATERMARK

        next_job = loader.new_job()
        loader.load(loader.messages(next_job, _WINDOW, final=True))

        assert loader.ids() == (_SEED_IDS if table_exists else []) + _WINDOW_IDS
        config = loader.config()
        assert config["incremental_field_last_value"] == max(_WINDOW_IDS)
        assert APPEND_RUN_MARKER_KEY not in config
        assert ExternalDataJob.objects.get(id=next_job.id).status == ExternalDataJob.Status.COMPLETED

    def test_a_retried_attempt_of_one_job_replaces_the_attempt_before_it(self, loader: _Loader) -> None:
        loader.seed()
        job = loader.new_job()
        first_attempt = loader.messages(job, _WINDOW, final=False)
        second_attempt = loader.messages(job, _WINDOW, attempt=2, final=True)

        loader.load(first_attempt[:2])
        loader.load(second_attempt[:1])
        # A batch that the first attempt queued arrives after the second attempt started to load.
        loader.load(first_attempt[2:])
        loader.load(second_attempt[1:])

        assert loader.ids() == _SEED_IDS + _WINDOW_IDS
        assert loader.config()["incremental_field_last_value"] == max(_WINDOW_IDS)

    def test_a_set_with_the_first_batch_of_the_next_run_loads_each_row_once(self, loader: _Loader) -> None:
        loader.seed()
        _cancelled(loader)

        process_messages(loader.messages(loader.new_job(), _WINDOW, final=True))

        assert loader.ids() == _SEED_IDS + _WINDOW_IDS

    @pytest.mark.parametrize("marker_survives_completion", [False, True])
    def test_a_completed_run_keeps_its_rows(self, loader: _Loader, marker_survives_completion: bool) -> None:
        loader.seed()
        first_job = loader.new_job()
        loader.load(loader.messages(first_job, [[3, 4]], final=False))
        marker = loader.config().get(APPEND_RUN_MARKER_KEY)
        loader.load(loader.messages(first_job, [[5, 6]], attempt=2, final=True, is_resume=True))
        if not marker_survives_completion:
            assert APPEND_RUN_MARKER_KEY not in loader.config()
        if marker_survives_completion:
            # A loader from before the marker completes the run and does not remove the marker.
            assert marker is not None
            config = loader.config()
            config[APPEND_RUN_MARKER_KEY] = marker
            ExternalDataSchema.objects.filter(id=loader.schema.id).update(sync_type_config=config)

        loader.load(loader.messages(loader.new_job(), [[7, 8]], final=True))

        assert loader.ids() == _SEED_IDS + _WINDOW_IDS
        assert loader.config()["incremental_field_last_value"] == 8
        assert "RESTORE" not in loader.operations()

    def test_a_later_completed_job_makes_an_old_marker_inert(self, loader: _Loader) -> None:
        loader.seed()
        failed_job = loader.new_job()
        loader.load(loader.messages(failed_job, [[3, 4]], final=False))
        old_marker = loader.config()[APPEND_RUN_MARKER_KEY]
        loader.fail(failed_job, "failed")

        loader.load(loader.messages(loader.new_job(), [[5, 6]], final=True))
        restore_count = loader.operations().count("RESTORE")
        config = loader.config()
        config[APPEND_RUN_MARKER_KEY] = old_marker
        ExternalDataSchema.objects.filter(id=loader.schema.id).update(sync_type_config=config)

        loader.load(loader.messages(loader.new_job(), [[7, 8]], final=True))

        assert loader.ids() == [*_SEED_IDS, 5, 6, 7, 8]
        assert loader.operations().count("RESTORE") == restore_count

    def test_a_fresh_attempt_of_a_completed_job_does_not_restore(self, loader: _Loader) -> None:
        loader.seed()
        job = loader.new_job()
        loader.load(loader.messages(job, [[3, 4]], final=False))
        old_marker = loader.config()[APPEND_RUN_MARKER_KEY]
        loader.load(loader.messages(job, [[5, 6]], attempt=2, final=True, is_resume=True))
        config = loader.config()
        config[APPEND_RUN_MARKER_KEY] = old_marker
        ExternalDataSchema.objects.filter(id=loader.schema.id).update(sync_type_config=config)

        loader.load(loader.messages(job, [[7, 8]], attempt=3, final=False))

        assert loader.ids() == _SEED_IDS + _WINDOW_IDS
        assert "RESTORE" not in loader.operations()

    def test_a_first_resumed_batch_records_the_job(self, loader: _Loader) -> None:
        loader.seed()
        job = loader.new_job()

        loader.load(loader.messages(job, [[3, 4]], attempt=2, final=False, is_resume=True))

        marker = loader.config()[APPEND_RUN_MARKER_KEY]
        assert marker["job_id"] == str(job.id)
        assert marker["run_uuid"] == f"{job.workflow_run_id}-a2"

    def test_rollback_can_be_disabled(self, loader: _Loader, settings: Any) -> None:
        settings.DATA_WAREHOUSE_APPEND_ROLLBACK_ENABLED = False
        loader.seed()

        loader.load(loader.messages(loader.new_job(), [[3, 4]], final=False))

        assert APPEND_RUN_MARKER_KEY not in loader.config()

    def test_a_permanent_restore_failure_uses_a_new_baseline(self, loader: _Loader) -> None:
        loader.seed()
        _failed_mid_run(loader)

        with patch(f"{_PROCESSOR}.DeltaWriter.restore", new_callable=AsyncMock, side_effect=RuntimeError("gone")):
            loader.load(loader.messages(loader.new_job(), _WINDOW, final=True))

        assert loader.ids().count(3) == 2
        assert loader.ids().count(4) == 2
        assert loader.config()["incremental_field_last_value"] == 8
        assert APPEND_RUN_MARKER_KEY not in loader.config()

    @pytest.mark.parametrize(
        "error",
        [CommitFailedError("concurrent commit"), DeltaError("Invalid table version: 2")],
        ids=["commit_conflict", "invalid_version_race"],
    )
    def test_a_racy_restore_failure_retries_the_batch(self, loader: _Loader, error: Exception) -> None:
        loader.seed()
        _failed_mid_run(loader)
        marker = loader.config()[APPEND_RUN_MARKER_KEY]

        with (
            patch(f"{_PROCESSOR}.DeltaWriter.restore", new_callable=AsyncMock, side_effect=error),
            pytest.raises(type(error)),
        ):
            loader.load(loader.messages(loader.new_job(), _WINDOW, final=True))

        assert loader.config()[APPEND_RUN_MARKER_KEY] == marker

    def test_an_older_completion_does_not_clear_a_newer_runs_marker(self, loader: _Loader) -> None:
        older_job = loader.new_job()
        older_run = loader.messages(older_job, [[3]], final=False)[0]["run_uuid"]
        loader.load([loader.messages(loader.new_job(), [[4]], final=False)[0]])
        current_marker = loader.config()[APPEND_RUN_MARKER_KEY]

        clear_append_run_marker(str(loader.schema.id), loader.team.id, str(older_job.id), older_run)

        assert loader.config()[APPEND_RUN_MARKER_KEY] == current_marker

    def test_a_replaced_table_is_not_restored(self, loader: _Loader, tmp_path: Path) -> None:
        loader.seed()
        _cancelled(loader)
        # A repartition swap puts a rewritten table, with a new id and new versions, at the same location.
        rows = DeltaTable(loader.table_path).to_pyarrow_table()
        loader.table_path = str(tmp_path / "swapped")
        write_deltalake(loader.table_path, rows.slice(0, 2))
        write_deltalake(loader.table_path, rows.slice(2), mode="append")

        loader.load(loader.messages(loader.new_job(), [[9]], final=True))

        existing_ids = cast(list[int], rows.column("id").to_pylist())
        assert loader.ids() == sorted([*existing_ids, 9])
        assert "RESTORE" not in loader.operations()


@pytest.mark.django_db
def test_an_incremental_run_after_a_failed_run_does_not_restore_the_table(team: Team, tmp_path: Path) -> None:
    loader = _Loader(team, str(tmp_path / "table"), sync_type="incremental")
    with (
        patch(f"{_PROCESSOR}.read_parquet", side_effect=lambda path: loader._batches[path]),
        patch(f"{_PROCESSOR}.DeltaTableRef", side_effect=lambda **kwargs: make_local_table_ref(loader.table_path)),
    ):
        loader.seed()
        failed_job = loader.new_job()
        loader.load(loader.messages(failed_job, _WINDOW[:2], final=False))
        loader.fail(failed_job, "connection to the source was lost")

        loader.load(loader.messages(loader.new_job(), _WINDOW, final=True))

    assert loader.ids() == _SEED_IDS + _WINDOW_IDS
    assert "RESTORE" not in loader.operations()
    assert APPEND_RUN_MARKER_KEY not in loader.config()
