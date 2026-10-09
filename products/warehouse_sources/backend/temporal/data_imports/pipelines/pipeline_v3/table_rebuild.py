from typing import Any

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)

TABLE_REBUILD_RUN_KEY = "table_rebuild_run_uuid"


def attempt_of(run_uuid: str) -> tuple[str, int] | None:
    """Split `<workflow run id>-a<attempt>`, the run id format of the extract pipeline."""
    workflow_run_id, separator, attempt = run_uuid.rpartition("-a")
    if not separator or not workflow_run_id or not attempt.isdigit():
        return None
    return workflow_run_id, int(attempt)


class TableRebuildRun:
    """The newest attempt that loads an incremental table from empty.

    Such an attempt reads the source from the start. Its first batch overwrites the table and its
    later batches append, because no row of the table can hold a key that the attempt has not
    written itself. The record lets a later attempt of the same workflow run load the same way, and
    lets the loader drop the batches of an attempt that a later one replaced: those batches would
    append rows that the newer attempt also appends.
    """

    def __init__(self, config: dict[str, Any] | None) -> None:
        raw = (config or {}).get(TABLE_REBUILD_RUN_KEY)
        self._attempt = attempt_of(raw) if isinstance(raw, str) else None

    def started_in(self, workflow_run_id: str | None) -> bool:
        """Whether an attempt of `workflow_run_id` started to rebuild the table."""
        return self._attempt is not None and workflow_run_id is not None and self._attempt[0] == workflow_run_id

    def replaces(self, run_uuid: str) -> bool:
        """Whether `run_uuid` is an earlier attempt of the workflow run that rebuilds the table."""
        candidate = attempt_of(run_uuid)
        if self._attempt is None or candidate is None:
            return False
        return self._attempt[0] == candidate[0] and candidate[1] < self._attempt[1]

    @staticmethod
    def record(schema: ExternalDataSchema, run_uuid: str) -> None:
        update_sync_type_config_keys(schema.id, schema.team_id, updates={TABLE_REBUILD_RUN_KEY: run_uuid})
        # The run saves this copy of the config again later, and that save must keep the record.
        schema.sync_type_config[TABLE_REBUILD_RUN_KEY] = run_uuid
