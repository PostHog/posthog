"""Open delta-rs handles that the loader keeps between consecutive batches of one run.

A delta-rs open of a table reads the last checkpoint and every commit after it, which is one
listing and tens of reads against object storage, plus the snapshot build. The loader makes a new
`DeltaTableRef` for each batch, so without this module each batch pays that open again for a table
the same thread wrote a moment ago.

A handle is kept only for the next batch of the same run in the same group, and it catches up with
one incremental log read before any caller reads it (see `DeltaTableRef.adopt_open_table`). Every
other batch opens the table: the first batch of a group run, batch 0, a redelivery, a batch of
another run, and the batch after any failure. The steps that replace a table under its URI (a
reset, a repartition swap, a corruption revive) run before a run stages its first batch, so the
table cannot be replaced between two batches that this rule joins.
"""

import time
import threading
from collections.abc import Callable

import deltalake

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage

# A handle that waited longer than this for its next batch is released. Consecutive batches of one
# group run follow each other at once, so a longer wait means the group run ended without a release.
RETAINED_HANDLE_MAX_IDLE_SECONDS = 60.0


@frozen
class _RetainedHandle:
    table: deltalake.DeltaTable
    job_id: str
    run_uuid: str
    resource_name: str
    last_batch_index: int
    retained_at: float


class GroupTableHandles:
    """At most one retained handle for each (team, schema) group, safe to share across worker threads.

    The queue runs one batch of a group at a time, so the number of retained handles never exceeds
    the number of groups in flight, which is also the number of handles open without this class.
    """

    def __init__(
        self,
        *,
        max_idle_seconds: float = RETAINED_HANDLE_MAX_IDLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_idle_seconds = max_idle_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._handles: dict[tuple[int, str], _RetainedHandle] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._handles)

    def take(self, export_signal: ExportSignalMessage, *, attempt: int) -> deltalake.DeltaTable | None:
        """Remove the group's handle and return it when this batch is the one it was kept for.

        The handle leaves the registry in every case. A batch that fails thus leaves nothing
        behind, and its retry opens the table.
        """
        with self._lock:
            self._release_idle()
            retained = self._handles.pop(_group_key(export_signal), None)
        if retained is None or attempt > 1:
            return None
        if (
            retained.job_id != export_signal.job_id
            or retained.run_uuid != export_signal.run_uuid
            or retained.resource_name != export_signal.resource_name
            or export_signal.batch_index != retained.last_batch_index + 1
        ):
            return None
        return retained.table

    def retain(self, export_signal: ExportSignalMessage, table: deltalake.DeltaTable, *, last_batch_index: int) -> None:
        """Keep `table` for the batch that follows `last_batch_index` in the same run."""
        with self._lock:
            self._release_idle()
            self._handles[_group_key(export_signal)] = _RetainedHandle(
                table=table,
                job_id=export_signal.job_id,
                run_uuid=export_signal.run_uuid,
                resource_name=export_signal.resource_name,
                last_batch_index=last_batch_index,
                retained_at=self._clock(),
            )

    def release(self, team_id: int, schema_id: str) -> None:
        with self._lock:
            self._handles.pop((team_id, str(schema_id)), None)

    def _release_idle(self) -> None:
        now = self._clock()
        for key, retained in list(self._handles.items()):
            if now - retained.retained_at > self._max_idle_seconds:
                del self._handles[key]


def _group_key(export_signal: ExportSignalMessage) -> tuple[int, str]:
    return export_signal.team_id, str(export_signal.schema_id)


GROUP_TABLE_HANDLES = GroupTableHandles()


def release_group_table_handle(team_id: int, schema_id: str) -> None:
    """Release the handle of a group whose run on this process ended."""
    GROUP_TABLE_HANDLES.release(team_id, schema_id)
