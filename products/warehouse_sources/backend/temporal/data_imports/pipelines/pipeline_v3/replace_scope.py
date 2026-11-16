"""Both halves of a run's replace scope: the manifest the extract side writes and the loader reads,
and the record that lets the loader drop the batches of an attempt that a later attempt replaced.

See `ReplaceScope` for what the loader does with a scope.
"""

from typing import Any

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    attempt_of,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import ReplaceScope

REPLACE_SCOPE_RUN_KEY = "replace_scope_run_uuid"
MANIFEST_FILE_NAME = "replace_scope.parquet"
_REPLACED_COLUMN = "replaced"
_RETAINED_COLUMN = "retained"


def manifest_table(scope: ReplaceScope) -> pa.Table:
    """The two value sets as two columns. The shorter column is padded with nulls."""
    replaced, retained = sorted(scope.replaced), sorted(scope.retained)
    length = max(len(replaced), len(retained))
    return pa.table(
        {
            _REPLACED_COLUMN: pa.array(replaced + [None] * (length - len(replaced)), pa.string()),
            _RETAINED_COLUMN: pa.array(retained + [None] * (length - len(retained)), pa.string()),
        }
    )


def scope_from_manifest(column: str, table: pa.Table) -> ReplaceScope:
    def values(name: str) -> frozenset[str]:
        return frozenset(value for value in table.column(name).to_pylist() if value is not None)

    return ReplaceScope(column=column, replaced=values(_REPLACED_COLUMN), retained=values(_RETAINED_COLUMN))


class ReplaceScopeRun:
    """The newest attempt of a workflow run whose first batch applied a replace scope.

    That batch deleted the rows of every file the attempt reads, which includes every file an
    earlier attempt of the same run read. A batch of an earlier attempt that loads afterwards would
    put rows back that the newer attempt also appends, so the loader drops it.
    """

    def __init__(self, config: dict[str, Any] | None) -> None:
        raw = (config or {}).get(REPLACE_SCOPE_RUN_KEY)
        self._attempt = attempt_of(raw) if isinstance(raw, str) else None

    def replaces(self, run_uuid: str) -> bool:
        """Whether `run_uuid` is an earlier attempt of the workflow run that applied the scope."""
        candidate = attempt_of(run_uuid)
        if self._attempt is None or candidate is None:
            return False
        return self._attempt[0] == candidate[0] and candidate[1] < self._attempt[1]

    @staticmethod
    def record(schema: ExternalDataSchema, run_uuid: str) -> None:
        schema.sync_type_config = update_sync_type_config_keys(
            schema.id, schema.team_id, updates={REPLACE_SCOPE_RUN_KEY: run_uuid}
        )
