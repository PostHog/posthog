"""Remove the rows that unfinished append runs left in one warehouse table.

An append run commits each batch to the Delta table, and its watermark moves only when the run
completes. A run that ended before its final batch left its rows in the table, and the next run
loaded the same range again. This command removes the copy of the runs that ended early. It deletes
customer data, so read the plan of the dry run before each execution.

It refuses when a sync of the schema runs, when the loader has a rollback of its own to do, when a
run id is not in the Delta log, and when the row counts do not agree. The Delta log, the table and
`--expected-rows` must give the same number of rows.

It takes the pipeline lock of the schema for the whole execution. After the change it publishes the
query copy of the table again and updates the row count and the size of the table record. It does
not repair external destinations. The DuckLake copy changes at the next completed sync.

`--undo-to-version` restores the Delta table to the version that the execution printed. It is
permitted only while the repair is the last commit of the table, because a restore also removes the
rows of each later sync. The removed files stay in storage for the vacuum retention only.

Usage:
    # Dry run (default): prints the plan, changes nothing
    python manage.py repair_append_duplicates --team-id 1 --schema-id <uuid> \\
        --run-uuid <run> --run-uuid <run> --expected-rows 1000

    # Execution. --mode rows permits a rewrite of the files that a compaction made.
    python manage.py repair_append_duplicates ... --mode rows --execute

    # Undo the execution
    python manage.py repair_append_duplicates --team-id 1 --schema-id <uuid> --undo-to-version 42 --execute
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any, Protocol, TypeVar
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import deltalake
import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.uuidt import uuid7

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import _publish_queryable_files
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.append_duplicate_repair import (
    AppendDuplicateRepair,
    RepairMode,
    RepairPlan,
    RepairRefused,
    RepairRequest,
    RepairResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    DeltaTableRef,
    build_delta_table_uri,
    delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import resolve_table_and_folder_names
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    _record_query_folder_pointer,
    own_linked_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    acquire_v3_pipeline_lock,
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
    write_v3_pipeline_lock_meta,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# The loader records an unfinished append run under this key, and restores the table to the recorded
# version at the next run. That restore puts back the files that a repair after it removed.
PENDING_ROLLBACK_KEY = "append_run_in_progress"
# Commit files stay in the Delta log for 30 days, so no older job can own a run that is still there.
COMPLETED_JOB_WINDOW = timedelta(days=45)


@frozen
class SchemaState:
    sync_type: str | None
    running_job_ids: tuple[str, ...]
    pending_rollback_run_uuid: str | None
    completed_workflow_run_ids: frozenset[str]


@frozen
class PublishedCopy:
    queryable_folder: str
    row_count: int | None
    size_mib: float | None


class RepairEnvironment(Protocol):
    """What the repair needs from outside the Delta table: the schema, the lock and the publish step."""

    def schema_state(self) -> SchemaState: ...

    def lock_holder(self) -> str | None: ...

    def acquire_lock(self, token: str) -> bool: ...

    def release_lock(self, token: str) -> None: ...

    def open_table(self) -> deltalake.DeltaTable | None: ...

    def publish(self) -> PublishedCopy: ...


class SchemaAppendDuplicateRepair:
    """Runs one repair of one schema: the refusals, the lock, the change, then the publish step."""

    def __init__(self, environment: RepairEnvironment, write: Callable[[str], None]) -> None:
        self._environment = environment
        self._write = write

    def run(self, request: RepairRequest, *, execute: bool, publish: bool = True) -> RepairPlan | RepairResult:
        return self._with_lock(
            execute, lambda token: self._run_locked(request, token, execute=execute, publish=publish)
        )

    def undo(self, version_before: int, *, execute: bool, publish: bool = True) -> int:
        """Restore the table to the version before the last repair, then publish it again."""
        return self._with_lock(execute, lambda token: self._undo_locked(version_before, token, execute, publish))

    def _with_lock(self, execute: bool, action: Callable[[str], T]) -> T:
        token = str(uuid7())
        if execute:
            if not self._environment.acquire_lock(token):
                raise RepairRefused(
                    "sync_running",
                    f"the pipeline lock of the schema is held by {self._environment.lock_holder()}",
                )
        else:
            holder = self._environment.lock_holder()
            if holder is not None:
                raise RepairRefused("sync_running", f"the pipeline lock of the schema is held by {holder}")
        try:
            return action(token)
        finally:
            if execute:
                self._environment.release_lock(token)

    def _open_idle_table(self) -> tuple[SchemaState, deltalake.DeltaTable]:
        state = self._environment.schema_state()
        if state.running_job_ids:
            raise RepairRefused("sync_running", f"job {', '.join(state.running_job_ids)} of the schema is running")
        table = self._environment.open_table()
        if table is None:
            raise RepairRefused("no_delta_table", "the schema has no Delta table")
        return state, table

    def _undo_locked(self, version_before: int, token: str, execute: bool, publish: bool) -> int:
        _, table = self._open_idle_table()
        rows = AppendDuplicateRepair(table).undo(version_before, execute=execute)
        if not execute:
            self._write(f"Dry run. The table has {rows} rows. Use --execute to restore it to version {version_before}.")
            return rows
        logger.info("append_duplicate_repair_undone", delta_version=version_before, rows=rows)
        self._write(f"restored to version {version_before}: {rows} rows")
        self._publish(token, publish)
        return rows

    def _run_locked(
        self, request: RepairRequest, token: str, *, execute: bool, publish: bool
    ) -> RepairPlan | RepairResult:
        state, table = self._open_idle_table()
        if state.sync_type != ExternalDataSchema.SyncType.APPEND:
            raise RepairRefused("not_append", f"the sync type of the schema is {state.sync_type}")
        if state.pending_rollback_run_uuid is not None:
            raise RepairRefused(
                "rollback_pending",
                f"the loader will restore the table at the next sync to remove run {state.pending_rollback_run_uuid}. "
                "That restore undoes a repair. Let that sync complete, then run the dry run again.",
            )

        repair = AppendDuplicateRepair(table)
        plan = repair.plan(
            RepairRequest(
                run_uuids=request.run_uuids,
                expected_rows=request.expected_rows,
                mode=request.mode,
                tolerance=request.tolerance,
                load_ids=request.load_ids,
                completed_workflow_run_ids=state.completed_workflow_run_ids,
            )
        )
        for line in plan.describe():
            self._write(line)
        if not execute:
            self._write("Dry run. No change was made. Use --execute to make the change.")
            return plan

        logger.info(
            "append_duplicate_repair_starting",
            run_uuids=plan.run_uuids,
            delta_version_before=plan.version_before,
            method=plan.method,
            rows_to_remove=plan.rows_to_remove,
        )
        result = repair.execute(plan)
        logger.info(
            "append_duplicate_repair_done",
            status=result.status,
            delta_version_before=result.version_before,
            delta_version_after=result.version_after,
            rows_removed=result.rows_removed,
        )
        self._write(
            f"{result.status}: version {result.version_before} -> {result.version_after}, "
            f"rows {result.rows_before} -> {result.rows_after}, files removed {result.files_removed}, "
            f"files written {result.files_added}"
        )
        self._write(f"To undo, while no sync has run since: --undo-to-version {result.version_before} --execute")

        self._publish(token, publish)
        return result

    def _publish(self, token: str, publish: bool) -> None:
        if not publish:
            self._write("Publish step skipped. The next completed sync publishes the table.")
        elif self._environment.lock_holder() != token:
            # A sync that took the lock publishes the table when it completes, and two publish steps
            # at the same time can leave the query folder pointer on a folder that is not complete.
            self._write("The pipeline lock was lost. Publish step skipped; the sync that holds it publishes the table.")
        else:
            published = self._environment.publish()
            self._write(
                f"published: folder {published.queryable_folder}, row count {published.row_count}, "
                f"size {published.size_mib} MiB"
            )


class DjangoRepairEnvironment:
    def __init__(self, team_id: int, schema_id: str) -> None:
        self._team_id = team_id
        self._schema_id = schema_id

    def _schema(self) -> ExternalDataSchema:
        return (
            ExternalDataSchema.objects.select_related("source", "table")
            .exclude(deleted=True)
            .get(id=self._schema_id, team_id=self._team_id)
        )

    def _folder_name(self, schema: ExternalDataSchema) -> str:
        return resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name).folder_name

    def schema_state(self) -> SchemaState:
        schema = self._schema()
        jobs = ExternalDataJob.objects.filter(
            team_id=self._team_id, schema_id=self._schema_id, created_at__gte=timezone.now() - COMPLETED_JOB_WINDOW
        )
        marker = (schema.sync_type_config or {}).get(PENDING_ROLLBACK_KEY)
        return SchemaState(
            sync_type=schema.sync_type,
            running_job_ids=tuple(
                str(job_id)
                for job_id in jobs.filter(status=ExternalDataJob.Status.RUNNING).values_list("id", flat=True)
            ),
            pending_rollback_run_uuid=str(marker.get("run_uuid")) if isinstance(marker, dict) else None,
            completed_workflow_run_ids=frozenset(
                run_id
                for run_id in jobs.filter(status=ExternalDataJob.Status.COMPLETED).values_list(
                    "workflow_run_id", flat=True
                )
                if run_id
            ),
        )

    def lock_holder(self) -> str | None:
        return get_v3_pipeline_lock_holder(self._team_id, self._schema_id)

    def acquire_lock(self, token: str) -> bool:
        if not acquire_v3_pipeline_lock(self._team_id, self._schema_id, token):
            return False
        # No workflow has this id, so a sync that looks at the holder cannot tell that it ended, and
        # leaves the lock alone.
        write_v3_pipeline_lock_meta(
            self._team_id, self._schema_id, run_id=token, workflow_id=f"append-duplicate-repair-{self._schema_id}"
        )
        return True

    def release_lock(self, token: str) -> None:
        release_v3_pipeline_lock(self._team_id, self._schema_id, token)

    def open_table(self) -> deltalake.DeltaTable | None:
        schema = self._schema()
        uri = build_delta_table_uri(schema.folder_path(), self._folder_name(schema))
        storage_options = delta_storage_options()
        if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
            return None
        return deltalake.DeltaTable(uri, storage_options=storage_options)

    def publish(self) -> PublishedCopy:
        schema = self._schema()
        job = (
            ExternalDataJob.objects.select_related("pipeline", "schema", "schema__source", "schema__table")
            .filter(team_id=self._team_id, schema_id=self._schema_id)
            .order_by("-created_at")
            .first()
        )
        if job is None:
            raise CommandError("The schema has no job, so the publish step cannot find the table folder")
        resource_name = self._folder_name(schema)
        table_ref = DeltaTableRef(resource_name=resource_name, job=job, logger=logger)

        async def publish_and_measure() -> PublishedCopy:
            folder = await _publish_queryable_files(job, schema, table_ref, resource_name, False, logger)
            return PublishedCopy(
                queryable_folder=folder,
                row_count=await table_ref.get_live_row_count(),
                size_mib=await table_ref.get_live_size_mib(),
            )

        published = async_to_sync(publish_and_measure)()
        table = own_linked_table(schema, job.pipeline)
        if table is None:
            raise CommandError("The schema has no table record. The files are published, but nothing points at them.")
        previous_folder = table.queryable_folder
        table.queryable_folder = published.queryable_folder
        update_fields = ["queryable_folder"]
        if published.row_count is not None:
            table.row_count = published.row_count
            update_fields.append("row_count")
        if published.size_mib is not None:
            table.size_in_s3_mib = published.size_mib
            update_fields.append("size_in_s3_mib")
        table.save(update_fields=update_fields)
        _record_query_folder_pointer(
            schema.id, self._team_id, previous_folder, published.queryable_folder, str(job.id), logger
        )
        return published


class Command(BaseCommand):
    help = "Remove the rows that unfinished append runs left in one warehouse table (dry run by default)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--schema-id", type=UUID, required=True)
        parser.add_argument(
            "--run-uuid",
            action="append",
            default=None,
            help="Run that ended before its final batch (<workflow run id>-a<attempt>). Repeatable.",
        )
        parser.add_argument(
            "--expected-rows",
            type=int,
            default=None,
            help="Rows that the given runs loaded, from the queue data. The Delta log and the table must agree.",
        )
        parser.add_argument(
            "--mode",
            choices=["files", "rows"],
            default="files",
            help="files: remove whole files only, and refuse when a compaction rewrote them. "
            "rows: also rewrite the files that hold rows of other runs.",
        )
        parser.add_argument(
            "--tolerance",
            type=int,
            default=0,
            help="Permitted difference between --expected-rows and the table. The Delta log and the table must "
            "always agree exactly.",
        )
        parser.add_argument(
            "--load-id",
            type=int,
            action="append",
            default=None,
            help="Load id of the rows to remove, for a table whose Delta log no longer has the runs. Repeatable.",
        )
        parser.add_argument(
            "--undo-to-version",
            type=int,
            default=None,
            help="Restore the table to this version, which the execution printed. Permitted only while the "
            "repair is the last commit of the table.",
        )
        parser.add_argument("--execute", action="store_true", help="Make the change (default is a dry run).")
        parser.add_argument(
            "--skip-publish",
            action="store_true",
            help="Do not publish the query copy of the table. The next completed sync publishes it.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        environment = DjangoRepairEnvironment(options["team_id"], str(options["schema_id"]))
        repair = SchemaAppendDuplicateRepair(environment, self.stdout.write)
        publish = not options["skip_publish"]
        try:
            if options["undo_to_version"] is not None:
                repair.undo(options["undo_to_version"], execute=options["execute"], publish=publish)
                return
            if not options["run_uuid"] or options["expected_rows"] is None:
                raise CommandError("Give --run-uuid and --expected-rows, or --undo-to-version")
            self._repair(repair, options, publish)
        except ExternalDataSchema.DoesNotExist as e:
            raise CommandError("No such schema for this team") from e
        except RepairRefused as e:
            raise CommandError(f"REFUSED {e}") from e

    def _repair(self, repair: SchemaAppendDuplicateRepair, options: dict[str, Any], publish: bool) -> None:
        mode: RepairMode = options["mode"]
        request = RepairRequest(
            run_uuids=tuple(dict.fromkeys(options["run_uuid"])),
            expected_rows=options["expected_rows"],
            mode=mode,
            tolerance=options["tolerance"],
            load_ids=tuple(options["load_id"] or ()),
        )
        repair.run(request, execute=options["execute"], publish=publish)
