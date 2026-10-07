"""Removes the rows of an append run that did not complete, before the next run loads.

An append run commits each batch to the table, but its watermark moves only when the whole run
completes. A run that ends early leaves its rows in the table and the watermark where it was, so the
next run reads the same rows again and an append has no key to merge them on. The loader therefore
records the table version at the first batch of each run. When the first batch of the next run finds
a recorded run that never completed, it restores the table to that version and then appends.
"""

from typing import Any

from django.conf import settings

import structlog
import deltalake.exceptions
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    APPEND_RUN_MARKER_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_invalid_version_race,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    APPEND_ROLLBACK_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import ExportSignalMessage

logger = structlog.get_logger(__name__)


@frozen
class AppendRunMarker:
    """The append run that the loader started to write, and the table as it was before that run."""

    job_id: str
    run_uuid: str
    # None when no table existed. The run then created the table, and version 0 of it is empty.
    table_id: str | None
    version: int | None

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "AppendRunMarker | None":
        raw = (config or {}).get(APPEND_RUN_MARKER_KEY)
        if not isinstance(raw, dict):
            return None
        job_id, run_uuid, table_id, version = (raw.get(key) for key in ("job_id", "run_uuid", "table_id", "version"))
        if not isinstance(job_id, str) or not isinstance(run_uuid, str):
            return None
        if not isinstance(table_id, str | None) or not isinstance(version, int | None):
            return None
        return cls(job_id=job_id, run_uuid=run_uuid, table_id=table_id, version=version)

    def to_config(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "run_uuid": self.run_uuid, "table_id": self.table_id, "version": self.version}


def _attempt_of(run_uuid: str) -> tuple[str, int] | None:
    """Split `<workflow run id>-a<attempt>`, the run id format of the extract pipeline."""
    workflow_run_id, separator, attempt = run_uuid.rpartition("-a")
    if not separator or not workflow_run_id or not attempt.isdigit():
        return None
    return workflow_run_id, int(attempt)


def clear_append_run_marker(schema_id: str, team_id: int, job_id: str, run_uuid: str) -> None:
    def clear_if_owned(config: dict[str, Any]) -> None:
        marker = AppendRunMarker.from_config(config)
        if marker is not None and (marker.job_id == job_id or marker.run_uuid == run_uuid):
            config.pop(APPEND_RUN_MARKER_KEY, None)

    update_sync_type_config_keys(schema_id, team_id, mutate=clear_if_owned)


class UnfinishedAppendRuns:
    """Tracks the append run in progress on one table, and removes the rows of a run that ended early."""

    def __init__(self, schema: ExternalDataSchema, delta_table_ref: DeltaTableRef) -> None:
        self._schema = schema
        self._delta_table_ref = delta_table_ref

    def _marker(self) -> AppendRunMarker | None:
        return AppendRunMarker.from_config(self._schema.sync_type_config)

    def is_replaced_attempt(self, run_uuid: str) -> bool:
        """Whether a later attempt of the same workflow run already started to load.

        That attempt reads the source again from the stored watermark, and its first batch removed
        the rows of the attempts before it. A batch of an earlier attempt that arrives afterwards
        would put those rows back.
        """
        if not settings.DATA_WAREHOUSE_APPEND_ROLLBACK_ENABLED:
            return False
        marker = self._marker()
        if marker is None or marker.run_uuid == run_uuid:
            return False
        current, candidate = _attempt_of(marker.run_uuid), _attempt_of(run_uuid)
        if current is None or candidate is None:
            return False
        return current[0] == candidate[0] and candidate[1] < current[1]

    def start_run(self, export_signal: ExportSignalMessage) -> None:
        """Call before the write of each append batch. Acts on the first batch of a new run only.

        A resumed attempt continues from the cursor of the attempt before it and keeps that
        attempt's rows, so it also keeps the recorded run.
        """
        if not settings.DATA_WAREHOUSE_APPEND_ROLLBACK_ENABLED or export_signal.batch_index != 0:
            return
        marker = self._marker()
        if marker is not None and (
            marker.run_uuid == export_signal.run_uuid
            or (export_signal.is_resume and marker.job_id == export_signal.job_id)
        ):
            return

        delta_table = async_to_sync(self._delta_table_ref.get_delta_table)()
        if (
            not export_signal.is_resume
            and marker is not None
            and delta_table is not None
            and self._never_completed(marker)
        ):
            self._roll_back(marker, export_signal)
            delta_table = async_to_sync(self._delta_table_ref.get_delta_table)()

        # Written before the batch, so a crash between the two leaves a version that is still the
        # table without this run.
        table_id: object = delta_table.metadata().id if delta_table is not None else None
        started = AppendRunMarker(
            job_id=export_signal.job_id,
            run_uuid=export_signal.run_uuid,
            table_id=table_id if isinstance(table_id, str) else None,
            version=self._delta_table_ref.latest_known_version(delta_table) if delta_table is not None else None,
        )
        self._schema.sync_type_config = update_sync_type_config_keys(
            self._schema.id, self._schema.team_id, updates={APPEND_RUN_MARKER_KEY: started.to_config()}
        )

    def _never_completed(self, marker: AppendRunMarker) -> bool:
        """Whether every row written after the recorded version belongs to a run that did not complete.

        The check reads the job rows and does not trust the marker alone. A loader that does not
        know the marker can complete a run and leave the marker in place, and a restore would then
        delete rows that the watermark already covers.
        """
        team_id = self._schema.team_id
        recorded_job_created_at = (
            ExternalDataJob.objects.filter(id=marker.job_id, team_id=team_id)
            .exclude(status=ExternalDataJob.Status.COMPLETED)
            .values_list("created_at", flat=True)
            .first()
        )
        if recorded_job_created_at is None:
            return False
        return not ExternalDataJob.objects.filter(
            schema_id=self._schema.id,
            team_id=team_id,
            status=ExternalDataJob.Status.COMPLETED,
            created_at__gt=recorded_job_created_at,
            rows_synced__gt=0,
        ).exists()

    def _roll_back(self, marker: AppendRunMarker, export_signal: ExportSignalMessage) -> None:
        delta_table = async_to_sync(self._delta_table_ref.get_delta_table)()
        if delta_table is None:
            return
        log = logger.bind(
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
            run_uuid=export_signal.run_uuid,
            unfinished_job_id=marker.job_id,
            unfinished_run_uuid=marker.run_uuid,
        )
        current_table_id: object = delta_table.metadata().id
        if marker.table_id is not None and current_table_id != marker.table_id:
            # A repartition swap or a rebuild put a new table at this location. Its versions do not
            # relate to the recorded one.
            log.warning("append_rollback_skipped_table_replaced")
            return
        target_version = marker.version if marker.version is not None else 0
        current_version = self._delta_table_ref.latest_known_version(delta_table)
        if current_version <= target_version:
            return
        try:
            restore_metrics = async_to_sync(DeltaWriter(self._delta_table_ref).restore)(
                target_version,
                commit_metadata={"rolled_back_run_uuid": marker.run_uuid, "rolled_back_job_id": marker.job_id},
            )
        except (TransientObjectStoreError, ObjectStorePermissionDeniedError):
            APPEND_ROLLBACK_TOTAL.labels(outcome="retryable_failure").inc()
            raise
        except deltalake.exceptions.DeltaError as e:
            if isinstance(e, deltalake.exceptions.CommitFailedError) or is_invalid_version_race(e):
                APPEND_ROLLBACK_TOTAL.labels(outcome="retryable_failure").inc()
                raise
            APPEND_ROLLBACK_TOTAL.labels(outcome="permanent_failure").inc()
            log.exception("append_rollback_failed", target_version=target_version, current_version=current_version)
            capture_exception(e)
            return
        except Exception as e:
            APPEND_ROLLBACK_TOTAL.labels(outcome="permanent_failure").inc()
            # A retry cannot repair a missing baseline file. Continuing preserves the pre-rollout
            # behavior rather than permanently stopping every later sync of this table.
            log.exception("append_rollback_failed", target_version=target_version, current_version=current_version)
            capture_exception(e)
            return
        APPEND_ROLLBACK_TOTAL.labels(outcome="success").inc()
        log.info(
            "append_run_rolled_back",
            target_version=target_version,
            current_version=current_version,
            files_removed=restore_metrics.get("numRemovedFile"),
            files_restored=restore_metrics.get("numRestoredFile"),
        )
