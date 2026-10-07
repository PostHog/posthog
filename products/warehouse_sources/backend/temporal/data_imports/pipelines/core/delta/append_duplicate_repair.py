"""Removes the rows that an append run left in a Delta table when it ended before its final batch.

An append run commits each batch as it arrives, and its watermark moves only when the run completes.
A run that ended early left its rows in the table, and the next run loaded the same range again, so
the table holds those rows twice. This module removes the copy of the run that ended early.

Two facts identify that copy. Each loader commit carries the run in its commit metadata, and each row
carries the load id of its attempt in the `_ph_debug` column. The Delta log does not store the load
id, so the files that the commits of the run added give it.

The removal is one `DELETE` on the load ids. delta-rs drops a file that holds only matching rows
with a remove action and writes no new file, and it rewrites a file that a compaction made from more
than one attempt.
"""

import json
from collections.abc import Sequence
from typing import Any, Literal, cast
from urllib.parse import unquote

import pyarrow as pa
import deltalake
import pyarrow.fs as pafs
import pyarrow.compute as pc
import pyarrow.parquet as pq
from deltalake.fs import DeltaStorageHandler

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import live_row_count
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    _commit_metadata_layouts,
)

DEBUG_COLUMN = "_ph_debug"
REPAIRED_RUNS_KEY = "append_duplicate_repair_runs"
VERSION_BEFORE_KEY = "append_duplicate_repair_version_before"
RESTORED_KEY = "append_duplicate_repair_restored_from"
# The loader tags the restore that removes an unfinished append run with this key.
ROLLED_BACK_RUN_KEY = "rolled_back_run_uuid"

RepairMode = Literal["files", "rows"]


class RepairRefused(Exception):
    """The repair did not change the table. `reason` is a stable code, the message says why."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason


@frozen
class RepairRequest:
    run_uuids: tuple[str, ...]
    #: Rows of the unfinished runs, from the queue data. The Delta log and the table must agree.
    expected_rows: int
    mode: RepairMode = "files"
    #: Permitted difference between `expected_rows` and the table. The log and the table must
    #: always agree exactly.
    tolerance: int = 0
    #: Given by the operator when the log can no longer give the load ids.
    load_ids: tuple[int, ...] = ()
    #: Workflow runs of the schema whose job completed. Empty skips the checks that need them.
    completed_workflow_run_ids: frozenset[str] = frozenset()


@frozen
class RepairPlan:
    #: "already_repaired" when a repair or a loader rollback already removed the runs.
    status: Literal["ready", "already_repaired"]
    run_uuids: tuple[str, ...]
    version_before: int
    method: RepairMode | None = None
    load_ids: tuple[int, ...] = ()
    rows_before: int = 0
    rows_to_remove: int = 0
    #: None when the log could not give the number (the operator gave the load ids).
    rows_in_run_commits: int | None = None
    files_to_remove: int = 0
    #: Files of the runs that a later commit replaced. Their rows are in files to rewrite.
    files_rewritten_since: int = 0

    def describe(self) -> list[str]:
        if self.status == "already_repaired":
            return [f"already repaired: no change (table version {self.version_before})"]
        return [
            f"table version before: {self.version_before}",
            f"method: {self.method}",
            f"load ids: {', '.join(str(load_id) for load_id in self.load_ids)}",
            f"rows before: {self.rows_before}",
            f"rows to remove: {self.rows_to_remove}",
            f"rows in the commits of the runs: {self.rows_in_run_commits}",
            f"files to remove with no rewrite: {self.files_to_remove}",
            f"files of the runs that were rewritten since: {self.files_rewritten_since}",
            f"rows after: {self.rows_before - self.rows_to_remove}",
        ]


@frozen
class RepairResult:
    status: Literal["repaired", "already_repaired"]
    version_before: int
    version_after: int
    rows_before: int
    rows_after: int
    rows_removed: int = 0
    files_removed: int = 0
    files_added: int = 0


@frozen
class _AddedFile:
    path: str
    rows: int | None
    load_ids: frozenset[int] | None


def _debug_value(load_id: int) -> str:
    return f'{{"load_id": {load_id}}}'


def _load_id_of(value: Any) -> int | None:
    if isinstance(value, bytes):
        value = value.decode()
    if not isinstance(value, str):
        return None
    try:
        load_id = json.loads(value).get("load_id")
    except (ValueError, AttributeError):
        return None
    return load_id if isinstance(load_id, int) else None


def _metadata_value(commit: dict[str, Any], key: str) -> str | None:
    for layout in _commit_metadata_layouts(commit):
        value = layout.get(key)
        if isinstance(value, str):
            return value
    return None


def _commit_runs(commit: dict[str, Any]) -> set[str]:
    """The runs whose batches a loader commit wrote. A write of several batches can span runs."""
    runs: set[str] = set()
    run_uuid = _metadata_value(commit, "run_uuid")
    if run_uuid is not None:
        runs.add(run_uuid)
    members = _metadata_value(commit, "members")
    if members:
        runs.update(member.rpartition(":")[0] for member in members.split(",") if ":" in member)
    return runs


def _attempt_of(run_uuid: str) -> tuple[str, int] | None:
    """Split `<workflow run id>-a<attempt>`, the run id format of the extract pipeline."""
    workflow_run_id, separator, attempt = run_uuid.rpartition("-a")
    if not separator or not workflow_run_id or not attempt.isdigit():
        return None
    return workflow_run_id, int(attempt)


def _restore_target(commit: dict[str, Any]) -> int | None:
    if commit.get("operation") != "RESTORE":
        return None
    target = (commit.get("operationParameters") or {}).get("version")
    if not isinstance(target, str | int):
        return None
    try:
        return int(target)
    except ValueError:
        return None


class AppendDuplicateRepair:
    """Plans and executes the removal of unfinished append runs from one Delta table.

    `plan` only reads. `execute` makes one commit, checks the result, and restores the table to the
    version before the commit when a check fails. The caller must hold the schema's pipeline lock
    from the plan to the end of the execution.
    """

    def __init__(self, delta_table: deltalake.DeltaTable) -> None:
        self._table = delta_table

    def plan(self, request: RepairRequest) -> RepairPlan:
        if not request.run_uuids:
            raise RepairRefused("no_runs", "give one or more run ids")
        wanted = set(request.run_uuids)
        version_before = self._table.version()
        history = sorted(self._table.history(), key=lambda commit: commit["version"])
        live_commits = self._commits_not_undone(history)

        if self._already_repaired(wanted, history, live_commits):
            return RepairPlan(status="already_repaired", run_uuids=request.run_uuids, version_before=version_before)

        run_commits = [commit for commit in live_commits if _commit_runs(commit) & wanted]
        found = set().union(*(_commit_runs(commit) for commit in run_commits)) if run_commits else set()
        missing = sorted(wanted - found)
        mixed = sorted(found - wanted)
        log_is_usable = not missing and not mixed
        if not log_is_usable and not request.load_ids:
            if missing:
                raise RepairRefused(
                    "run_not_in_log",
                    f"no commit of {', '.join(missing)} is in the Delta log. The log expired, the table was "
                    "replaced, or the run id is wrong. Only --load-id can select the rows now.",
                )
            raise RepairRefused(
                "commit_spans_runs",
                f"a commit holds batches of these runs and of {', '.join(mixed)}. Its files mix the runs. "
                "Only --load-id can select the rows.",
            )

        if log_is_usable:
            self._check_runs_are_superseded(request, run_commits, live_commits)

        added_files = self._added_files(run_commits) if log_is_usable else []
        live_paths = {unquote(path) for path in self._table._table.get_add_file_sizes()}
        live_files = [file for file in added_files if file.path in live_paths]
        files_rewritten_since = len(added_files) - len(live_files)

        load_ids = tuple(sorted(set(request.load_ids) or self._load_ids_of(added_files)))
        method: RepairMode = "rows" if files_rewritten_since or not log_is_usable else "files"
        if method == "rows" and request.mode == "files":
            raise RepairRefused(
                "files_were_rewritten",
                f"{files_rewritten_since} of {len(added_files)} files of the runs are not live. A compaction or "
                "a repartition put their rows into other files. --mode rows rewrites those files.",
            )

        rows_in_run_commits = self._rows_added(run_commits, added_files) if log_is_usable else None
        rows_before = self._count_rows(None)
        rows_to_remove = self._count_rows(load_ids)
        self._check_counts(request, rows_to_remove, rows_in_run_commits)

        return RepairPlan(
            status="ready",
            run_uuids=request.run_uuids,
            version_before=version_before,
            method=method,
            load_ids=load_ids,
            rows_before=rows_before,
            rows_to_remove=rows_to_remove,
            rows_in_run_commits=rows_in_run_commits,
            files_to_remove=len(live_files),
            files_rewritten_since=files_rewritten_since,
        )

    def execute(self, plan: RepairPlan) -> RepairResult:
        if plan.status == "already_repaired":
            return RepairResult(
                status="already_repaired",
                version_before=plan.version_before,
                version_after=plan.version_before,
                rows_before=plan.rows_before,
                rows_after=plan.rows_before,
            )
        self._table.update_incremental()
        if self._table.version() != plan.version_before:
            raise RepairRefused(
                "table_changed",
                f"the table moved from version {plan.version_before} to {self._table.version()} after the plan",
            )

        values = ", ".join(f"'{_debug_value(load_id)}'" for load_id in plan.load_ids)
        metrics = self._table.delete(
            f"{DEBUG_COLUMN} IN ({values})",
            commit_properties=deltalake.CommitProperties(
                custom_metadata={
                    REPAIRED_RUNS_KEY: ",".join(plan.run_uuids),
                    VERSION_BEFORE_KEY: str(plan.version_before),
                }
            ),
        )
        self._table.update_incremental()
        rows_after = self._count_rows(None)
        rows_removed = int(metrics.get("num_deleted_rows") or 0)
        files_added = int(metrics.get("num_added_files") or 0)

        problems: list[str] = []
        if rows_removed != plan.rows_to_remove:
            problems.append(f"the commit removed {rows_removed} rows, the plan was {plan.rows_to_remove}")
        if rows_after != plan.rows_before - plan.rows_to_remove:
            problems.append(f"the table has {rows_after} rows, the plan was {plan.rows_before - plan.rows_to_remove}")
        if plan.method == "files" and (files_added or metrics.get("num_copied_rows")):
            problems.append("the commit rewrote a file, and the plan was to remove whole files only")
        if problems:
            self._table.restore(
                plan.version_before,
                commit_properties=deltalake.CommitProperties(
                    custom_metadata={RESTORED_KEY: str(self._table.version())}
                ),
            )
            raise RepairRefused(
                "post_check_failed",
                f"{'; '.join(problems)}. The table was restored to version {plan.version_before}.",
            )

        return RepairResult(
            status="repaired",
            version_before=plan.version_before,
            version_after=self._table.version(),
            rows_before=plan.rows_before,
            rows_after=rows_after,
            rows_removed=rows_removed,
            files_removed=int(metrics.get("num_removed_files") or 0),
            files_added=files_added,
        )

    @staticmethod
    def _commits_not_undone(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The commits whose changes are still in the table. A restore undoes each commit after its target."""
        kept: list[dict[str, Any]] = []
        for commit in history:
            target = _restore_target(commit)
            if target is not None:
                kept = [earlier for earlier in kept if earlier["version"] <= target]
            kept.append(commit)
        return kept

    @staticmethod
    def _already_repaired(wanted: set[str], history: list[dict[str, Any]], live_commits: list[dict[str, Any]]) -> bool:
        repaired: set[str] = set()
        for commit in live_commits:
            repaired.update((_metadata_value(commit, REPAIRED_RUNS_KEY) or "").split(","))
            rolled_back = _metadata_value(commit, ROLLED_BACK_RUN_KEY)
            if rolled_back:
                repaired.add(rolled_back)
        # A restore to a version before the first commit of a run removed that run too.
        in_history: set[str] = set().union(*(_commit_runs(commit) for commit in history))
        still_live: set[str] = set().union(*(_commit_runs(commit) for commit in live_commits))
        repaired.update(in_history - still_live)
        done = wanted & repaired
        if done and done != wanted:
            raise RepairRefused(
                "partially_repaired",
                f"{', '.join(sorted(done))} are already removed. Give only the runs that are still in the table.",
            )
        return bool(done)

    @staticmethod
    def _check_runs_are_superseded(
        request: RepairRequest, run_commits: list[dict[str, Any]], live_commits: list[dict[str, Any]]
    ) -> None:
        """Refuse runs that nothing loaded again, because their rows are then the only copy."""
        wanted = set(request.run_uuids)
        last_version = max(commit["version"] for commit in run_commits)
        later_runs = set().union(
            *(_commit_runs(commit) for commit in live_commits if commit["version"] > last_version), set()
        )
        if not later_runs:
            raise RepairRefused(
                "no_later_run",
                "no run wrote to the table after these runs, so no later run loaded their rows again",
            )
        completed = request.completed_workflow_run_ids
        if not completed:
            return
        all_runs = set().union(*(_commit_runs(commit) for commit in live_commits))
        for run_uuid in sorted(wanted):
            attempt = _attempt_of(run_uuid)
            if attempt is None or attempt[0] not in completed:
                continue
            has_later_attempt = any(
                other is not None and other[0] == attempt[0] and other[1] > attempt[1]
                for other in (_attempt_of(candidate) for candidate in all_runs - wanted)
            )
            if not has_later_attempt:
                raise RepairRefused(
                    "run_completed",
                    f"the job of {run_uuid} completed and no later attempt of it wrote to the table. "
                    "This run is the copy to keep.",
                )
        later_workflow_runs = {attempt[0] for attempt in map(_attempt_of, later_runs) if attempt is not None}
        if not later_workflow_runs & completed:
            raise RepairRefused(
                "no_completed_later_run",
                "no run that wrote to the table after these runs belongs to a completed job",
            )

    def _filesystem(self) -> pafs.FileSystem:
        """A file system at the table folder, with the credentials of the table."""
        handler = cast(pafs.FileSystemHandler, DeltaStorageHandler.from_table(self._table._table))
        return pafs.PyFileSystem(handler)

    def _added_files(self, run_commits: list[dict[str, Any]]) -> list[_AddedFile]:
        """The files that each commit added, from the commit files of the log."""
        filesystem = self._filesystem()
        files: list[_AddedFile] = []
        for commit in run_commits:
            with filesystem.open_input_stream(f"_delta_log/{commit['version']:020d}.json") as stream:
                lines = stream.read().decode().splitlines()
            for line in lines:
                add = json.loads(line).get("add") if line.strip() else None
                if not isinstance(add, dict):
                    continue
                stats = json.loads(add["stats"]) if isinstance(add.get("stats"), str) else {}
                low = _load_id_of((stats.get("minValues") or {}).get(DEBUG_COLUMN))
                high = _load_id_of((stats.get("maxValues") or {}).get(DEBUG_COLUMN))
                rows = stats.get("numRecords")
                files.append(
                    _AddedFile(
                        path=unquote(add["path"]),
                        rows=rows if isinstance(rows, int) else None,
                        load_ids=frozenset({low, high}) if low is not None and high is not None else None,
                    )
                )
        return files

    def _load_ids_of(self, added_files: Sequence[_AddedFile]) -> set[int]:
        """The load ids in the files of the runs. A table with many columns has no log statistic for
        the debug column, so the footer of the file gives it then."""
        load_ids: set[int] = set()
        filesystem: pafs.FileSystem | None = None
        for file in added_files:
            if file.load_ids is not None:
                load_ids.update(file.load_ids)
                continue
            if filesystem is None:
                filesystem = self._filesystem()
            try:
                load_ids.update(self._footer_load_ids(filesystem, file.path))
            except FileNotFoundError as e:
                raise RepairRefused(
                    "load_id_unknown",
                    f"the log has no load id for {file.path} and the file is gone. Give the load id with --load-id.",
                ) from e
        if not load_ids:
            raise RepairRefused("load_id_unknown", "the commits of the runs added no file with a load id")
        return load_ids

    @staticmethod
    def _footer_load_ids(filesystem: pafs.FileSystem, path: str) -> set[int]:
        metadata = pq.read_metadata(path, filesystem=filesystem)
        column = next(
            (index for index in range(metadata.num_columns) if metadata.schema.column(index).path == DEBUG_COLUMN),
            None,
        )
        if column is None:
            raise RepairRefused("no_debug_column", f"{path} has no {DEBUG_COLUMN} column")
        load_ids: set[int] = set()
        for group in range(metadata.num_row_groups):
            statistics = metadata.row_group(group).column(column).statistics
            if statistics is None or not statistics.has_min_max:
                raise RepairRefused("load_id_unknown", f"{path} has no statistic for {DEBUG_COLUMN}")
            for value in (statistics.min, statistics.max):
                load_id = _load_id_of(value)
                if load_id is None:
                    raise RepairRefused("load_id_unknown", f"{path} has a {DEBUG_COLUMN} value with no load id")
                load_ids.add(load_id)
        return load_ids

    @staticmethod
    def _rows_added(run_commits: list[dict[str, Any]], added_files: Sequence[_AddedFile]) -> int | None:
        if all(file.rows is not None for file in added_files):
            return sum(file.rows or 0 for file in added_files)
        total = 0
        for commit in run_commits:
            rows = (commit.get("operationMetrics") or {}).get("num_added_rows")
            if not isinstance(rows, int):
                return None
            total += rows
        return total

    def _count_rows(self, load_ids: Sequence[int] | None) -> int:
        if load_ids is None:
            from_log = live_row_count(self._table)
            if from_log is not None:
                return from_log
            return self._table.to_pyarrow_dataset().count_rows()
        dataset = self._table.to_pyarrow_dataset()
        if DEBUG_COLUMN not in dataset.schema.names:
            raise RepairRefused("no_debug_column", f"the table has no {DEBUG_COLUMN} column")
        values = pa.array([_debug_value(load_id) for load_id in load_ids], type=dataset.schema.field(DEBUG_COLUMN).type)
        return dataset.count_rows(filter=pc.field(DEBUG_COLUMN).isin(values))

    @staticmethod
    def _check_counts(request: RepairRequest, rows_to_remove: int, rows_in_run_commits: int | None) -> None:
        if rows_in_run_commits is not None and rows_in_run_commits != rows_to_remove:
            raise RepairRefused(
                "row_count_mismatch",
                f"the commits of the runs added {rows_in_run_commits} rows, but {rows_to_remove} rows in the table "
                "carry their load ids",
            )
        if abs(rows_to_remove - request.expected_rows) > request.tolerance:
            raise RepairRefused(
                "row_count_mismatch",
                f"{rows_to_remove} rows in the table carry the load ids of the runs, but {request.expected_rows} "
                f"rows were expected (tolerance {request.tolerance})",
            )
