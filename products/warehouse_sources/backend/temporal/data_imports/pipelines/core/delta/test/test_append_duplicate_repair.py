import tempfile
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import pyarrow as pa
import deltalake
from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    _append_debug_column_to_pyarrows_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.append_duplicate_repair import (
    AppendDuplicateRepair,
    RepairRefused,
    RepairRequest,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import (
    make_local_table_ref,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter

EARLIER = "wf0-a1"
UNFINISHED = "wf1-a1"
COMPLETED = "wf1-a2"
BATCH_ROWS = 10
UNFINISHED_ROWS = 2 * BATCH_ROWS


@contextmanager
def _tmp_dir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


class _Table:
    """A local Delta table that the loader's writer fills, one commit for each batch."""

    def __init__(self, tmp_path: Path, *, partitioned: bool = False, extra_columns: int = 0) -> None:
        self.uri = str(tmp_path / "table")
        self._ref = make_local_table_ref(self.uri)
        self._partitioned = partitioned
        self._extra_columns = extra_columns

    def load_run(self, run_uuid: str, load_id: int, batch_starts: list[int]) -> None:
        for batch_index, start in enumerate(batch_starts):
            ids = list(range(start, start + BATCH_ROWS))
            columns: dict[str, list] = {"id": ids}
            columns.update({f"c{n}": ids for n in range(self._extra_columns)})
            if self._partitioned:
                columns[PARTITION_KEY] = [f"p{row_id % 2}" for row_id in ids]
            async_to_sync(DeltaWriter(self._ref).write)(
                data=_append_debug_column_to_pyarrows_table(pa.table(columns), load_id),
                write_type="append",
                should_overwrite_table=False,
                primary_keys=None,
                commit_metadata={"run_uuid": run_uuid, "batch_index": str(batch_index)},
            )

    def load_duplicates(self) -> None:
        self.load_run(EARLIER, 1, [0])
        self.load_run(UNFINISHED, 2, [10, 20])
        self.load_run(COMPLETED, 3, [10, 20, 30])

    def open(self) -> deltalake.DeltaTable:
        return deltalake.DeltaTable(self.uri)

    def ids(self) -> list[int]:
        return sorted(self.open().to_pyarrow_table(columns=["id"])["id"].to_numpy().tolist())


def _request(*run_uuids: str, expected_rows: int = UNFINISHED_ROWS, **kwargs) -> RepairRequest:
    return RepairRequest(run_uuids=run_uuids or (UNFINISHED,), expected_rows=expected_rows, **kwargs)


class TestAppendDuplicateRepair:
    @parameterized.expand(
        [
            ("unpartitioned", False, False, 0, "files"),
            ("partitioned", True, False, 0, "files"),
            ("no_log_statistic_for_the_load_id", False, False, 40, "files"),
            ("unpartitioned_compacted", False, True, 0, "rows"),
            ("partitioned_compacted", True, True, 0, "rows"),
        ]
    )
    def test_removes_only_the_rows_of_the_unfinished_run(
        self, _name: str, partitioned: bool, compacted: bool, extra_columns: int, method: str
    ) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path, partitioned=partitioned, extra_columns=extra_columns)
            table.load_duplicates()
            if compacted:
                table.open().optimize.compact()
            assert len(table.ids()) == 60

            repair = AppendDuplicateRepair(table.open())
            plan = repair.plan(_request(mode="rows" if compacted else "files"))
            result = repair.execute(plan)

            assert plan.method == method
            assert table.ids() == list(range(40))
            assert (result.rows_before, result.rows_removed, result.rows_after) == (60, 20, 40)
            if method == "files":
                assert result.files_added == 0

    @parameterized.expand(
        [
            ("run_not_in_log", ("wf9-a1",), {}, False, "run_not_in_log"),
            ("last_run_of_the_table", (COMPLETED,), {"expected_rows": 30}, False, "no_later_run"),
            ("more_rows_expected", (UNFINISHED,), {"expected_rows": UNFINISHED_ROWS + 1}, False, "row_count_mismatch"),
            ("fewer_rows_expected", (UNFINISHED,), {"expected_rows": UNFINISHED_ROWS - 1}, False, "row_count_mismatch"),
            ("wrong_load_id", (UNFINISHED,), {"load_ids": (3,)}, False, "row_count_mismatch"),
            ("compacted_in_files_mode", (UNFINISHED,), {"mode": "files"}, True, "files_were_rewritten"),
        ]
    )
    def test_refuses_and_leaves_the_table_as_it_was(
        self, _name: str, run_uuids: tuple[str, ...], request_kwargs: dict, compacted: bool, reason: str
    ) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            if compacted:
                table.open().optimize.compact()
            version = table.open().version()

            with pytest.raises(RepairRefused) as refused:
                AppendDuplicateRepair(table.open()).plan(_request(*run_uuids, **request_kwargs))

            assert refused.value.reason == reason
            assert table.open().version() == version
            assert len(table.ids()) == 60

    @parameterized.expand(
        [
            ("attempt_that_completed", "wf1-a2", 30, "run_completed"),
            ("attempt_before_the_one_that_completed", "wf1-a1", 20, None),
            ("no_later_job_completed", "wf2-a1", 10, "no_completed_later_run"),
        ]
    )
    def test_uses_the_completed_jobs_to_protect_the_copy_to_keep(
        self, _name: str, run_uuid: str, expected_rows: int, reason: str | None
    ) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            table.load_run("wf2-a1", 4, [40])
            table.load_run("wf3-a1", 5, [40])
            repair = AppendDuplicateRepair(table.open())
            request = _request(
                run_uuid, expected_rows=expected_rows, completed_workflow_run_ids=frozenset({"wf0", "wf1"})
            )

            if reason is None:
                assert repair.plan(request).status == "ready"
            else:
                with pytest.raises(RepairRefused) as refused:
                    repair.plan(request)
                assert refused.value.reason == reason

    def test_second_execution_changes_nothing(self) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            first = AppendDuplicateRepair(table.open())
            first.execute(first.plan(_request()))
            version = table.open().version()

            second = AppendDuplicateRepair(table.open())
            plan = second.plan(_request())
            result = second.execute(plan)

            assert (plan.status, result.status) == ("already_repaired", "already_repaired")
            assert table.open().version() == version
            assert table.ids() == list(range(40))

    def test_repairs_again_after_a_restore_to_the_version_before(self) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            first = AppendDuplicateRepair(table.open())
            result = first.execute(first.plan(_request()))
            table.open().restore(result.version_before)
            assert len(table.ids()) == 60

            again = AppendDuplicateRepair(table.open())
            plan = again.plan(_request())
            again.execute(plan)

            assert plan.status == "ready"
            assert table.ids() == list(range(40))

    def test_load_id_selects_the_rows_when_the_log_has_no_commit_of_the_run(self) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            repair = AppendDuplicateRepair(table.open())

            plan = repair.plan(_request("run-with-no-commit", mode="rows", load_ids=(2,)))
            repair.execute(plan)

            assert plan.rows_in_run_commits is None
            assert table.ids() == list(range(40))

    def test_restores_the_table_when_the_commit_does_not_match_the_plan(self) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            repair = AppendDuplicateRepair(table.open())
            plan = repair.plan(_request())
            wrong_plan = dataclasses.replace(plan, rows_to_remove=plan.rows_to_remove - 1)

            with pytest.raises(RepairRefused) as refused:
                repair.execute(wrong_plan)

            assert refused.value.reason == "post_check_failed"
            assert len(table.ids()) == 60

    def test_refuses_to_execute_a_plan_after_another_commit(self) -> None:
        with _tmp_dir() as tmp_path:
            table = _Table(tmp_path)
            table.load_duplicates()
            repair = AppendDuplicateRepair(table.open())
            plan = repair.plan(_request())
            table.load_run("wf2-a1", 4, [40])

            with pytest.raises(RepairRefused) as refused:
                repair.execute(plan)

            assert refused.value.reason == "table_changed"
            assert len(table.ids()) == 70
