import tempfile

import pytest

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.management.commands.repair_append_duplicates import (
    PublishedCopy,
    SchemaAppendDuplicateRepair,
    SchemaState,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.append_duplicate_repair import (
    RepairRefused,
    RepairRequest,
)

_REQUEST = RepairRequest(run_uuids=("wf1-a1",), expected_rows=10)


def _append(uri: str, run_uuid: str, load_id: int, start: int) -> None:
    ids = list(range(start, start + 10))
    deltalake.write_deltalake(
        uri,
        pa.table({"id": ids, "_ph_debug": [f'{{"load_id": {load_id}}}'] * len(ids)}),
        mode="append",
        commit_properties=deltalake.CommitProperties(custom_metadata={"run_uuid": run_uuid, "batch_index": "0"}),
    )


class _Environment:
    def __init__(
        self,
        uri: str | None,
        *,
        sync_type: str = "append",
        running_job_ids: tuple[str, ...] = (),
        pending_rollback_run_uuid: str | None = None,
        lock_holder: str | None = None,
        lock_lost_during_repair: bool = False,
    ) -> None:
        self._uri = uri
        self._state = SchemaState(
            sync_type=sync_type,
            running_job_ids=running_job_ids,
            pending_rollback_run_uuid=pending_rollback_run_uuid,
            completed_workflow_run_ids=frozenset({"wf1"}),
        )
        self._holder = lock_holder
        self._lock_lost_during_repair = lock_lost_during_repair
        self.acquired: list[str] = []
        self.released: list[str] = []
        self.publish_count = 0

    def schema_state(self) -> SchemaState:
        return self._state

    def lock_holder(self) -> str | None:
        return self._holder

    def acquire_lock(self, token: str) -> bool:
        if self._holder is not None:
            return False
        self._holder = token
        self.acquired.append(token)
        return True

    def release_lock(self, token: str) -> None:
        self.released.append(token)
        if self._holder == token:
            self._holder = None

    def open_table(self) -> deltalake.DeltaTable | None:
        if self._uri is None:
            return None
        if self._lock_lost_during_repair:
            self._holder = "another-sync"
        return deltalake.DeltaTable(self._uri)

    def publish(self) -> PublishedCopy:
        self.publish_count += 1
        return PublishedCopy(queryable_folder="table__query_a", row_count=20, size_mib=0.1)


class TestSchemaAppendDuplicateRepair:
    @pytest.fixture(autouse=True)
    def _table(self):
        with tempfile.TemporaryDirectory() as directory:
            self.uri = f"{directory}/table"
            _append(self.uri, "wf0-a1", 1, 0)
            _append(self.uri, "wf1-a1", 2, 10)
            _append(self.uri, "wf1-a2", 3, 10)
            yield

    def _rows(self) -> int:
        return deltalake.DeltaTable(self.uri).count()

    @parameterized.expand(
        [
            ("lock_held_by_a_sync", True, {"lock_holder": "workflow-run"}, "sync_running"),
            ("lock_held_by_a_sync_in_a_dry_run", False, {"lock_holder": "workflow-run"}, "sync_running"),
            ("job_running", True, {"running_job_ids": ("job-1",)}, "sync_running"),
            ("loader_rollback_pending", True, {"pending_rollback_run_uuid": "wf1-a1"}, "rollback_pending"),
            ("not_an_append_schema", True, {"sync_type": "incremental"}, "not_append"),
            ("no_delta_table", True, {"no_table": True}, "no_delta_table"),
        ]
    )
    def test_refuses_and_changes_nothing(
        self, _name: str, execute: bool, environment_kwargs: dict, reason: str
    ) -> None:
        uri = None if environment_kwargs.pop("no_table", False) else self.uri
        environment = _Environment(uri, **environment_kwargs)

        with pytest.raises(RepairRefused) as refused:
            SchemaAppendDuplicateRepair(environment, lambda _line: None).run(_REQUEST, execute=execute)

        assert refused.value.reason == reason
        assert self._rows() == 30
        assert environment.publish_count == 0
        assert environment.released == environment.acquired

    def test_dry_run_changes_nothing_and_takes_no_lock(self) -> None:
        environment = _Environment(self.uri)
        lines: list[str] = []

        SchemaAppendDuplicateRepair(environment, lines.append).run(_REQUEST, execute=False)

        assert self._rows() == 30
        assert (environment.acquired, environment.publish_count) == ([], 0)
        assert "rows to remove: 10" in lines

    @parameterized.expand(
        [
            ("publishes_the_table", {}, True, 1),
            ("lock_lost_before_the_publish_step", {"lock_lost_during_repair": True}, True, 0),
            ("publish_step_skipped_by_the_operator", {}, False, 0),
        ]
    )
    def test_execution_removes_the_rows_then_publishes_under_the_lock(
        self, _name: str, environment_kwargs: dict, publish: bool, publish_count: int
    ) -> None:
        environment = _Environment(self.uri, **environment_kwargs)

        SchemaAppendDuplicateRepair(environment, lambda _line: None).run(_REQUEST, execute=True, publish=publish)

        assert self._rows() == 20
        assert environment.publish_count == publish_count
        assert len(environment.acquired) == 1
        assert environment.released == environment.acquired
