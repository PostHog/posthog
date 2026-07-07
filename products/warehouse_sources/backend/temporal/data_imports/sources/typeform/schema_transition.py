from typing import Any

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.typeform.settings import (
    RESPONSE_TYPE_COMPLETED_ONLY,
    SUBMITTED_AT_INCREMENTAL,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _response_types(job_inputs: dict[str, Any]) -> str:
    return job_inputs.get("response_types") or RESPONSE_TYPE_COMPLETED_ONLY


def detect_typeform_response_types_transition(
    *,
    source_type: ExternalDataSourceType,
    existing_job_inputs: dict[str, Any],
    incoming_job_inputs: dict[str, Any],
) -> bool:
    """True when this PATCH changes Typeform's `response_types` (completed-only ⇄ partials included).

    The two modes sync the responses table differently — completed-only is incremental on
    `submitted_at`, all-responses is full-refresh only (partial/started responses have no
    `submitted_at` and share no cursor). Switching therefore needs the responses schema rebuilt on
    the new sync type, so the caller must reset it (see `apply_typeform_response_types_reset`).
    """
    if source_type != ExternalDataSourceType.TYPEFORM:
        return False
    if "response_types" not in incoming_job_inputs:
        return False
    return _response_types(existing_job_inputs) != _response_types(incoming_job_inputs)


def apply_typeform_response_types_reset(
    source: ExternalDataSource, *, incoming_job_inputs: dict[str, Any]
) -> list[ExternalDataSchema]:
    """Reset the Typeform responses schema so the next run rebuilds it for the new response-type set.

    Flags `reset_pipeline` (the run deletes the table and clears watermark + partition config) and
    flips the sync type: full refresh with no cursor once partial/started responses are included,
    back to incremental on `submitted_at` for completed-only. Returns the schemas it reset so the
    caller can trigger an immediate resync after the source save commits.
    """
    include_partials = _response_types(incoming_job_inputs) != RESPONSE_TYPE_COMPLETED_ONLY
    rows = list(
        ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, name="responses", deleted=False)
    )
    for row in rows:
        config = row.sync_type_config or {}
        config["reset_pipeline"] = True
        # A watermark in the old field's units is meaningless on the rebuilt table, so drop it.
        config.pop("incremental_field_last_value", None)
        config.pop("incremental_field_earliest_value", None)
        if include_partials:
            # All-responses mode is full-refresh only: no cursor to track.
            row.sync_type = ExternalDataSchema.SyncType.FULL_REFRESH
            config.pop("incremental_field", None)
            config.pop("incremental_field_type", None)
        else:
            row.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
            config["incremental_field"] = SUBMITTED_AT_INCREMENTAL["field"]
            config["incremental_field_type"] = IncrementalFieldType.DateTime.value
        row.sync_type_config = config
        row.save()
    return rows
