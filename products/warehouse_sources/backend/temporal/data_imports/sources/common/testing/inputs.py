import datetime
from typing import Any

import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.types import IncrementalFieldType

_LOGGER_NAME = "source_testing"


def source_inputs(
    schema_name: str,
    *,
    team_id: int = 1,
    job_id: str = "00000000-0000-4000-8000-000000000003",
    should_use_incremental_field: bool | None = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
    db_incremental_field_last_value: object | None = None,
    db_incremental_field_earliest_value: object | None = None,
    db_incremental_field_last_value_before_lookback: object | None = None,
    reset_pipeline: bool = False,
    api_version: str | None = None,
    history_start: datetime.datetime | None = None,
    logger: FilteringBoundLogger | None = None,
    source_cursor: SourceCursorManager[Any] | None = None,
) -> SourceInputs:
    """The `SourceInputs` the pipeline hands a source, with the fields a test varies.

    `should_use_incremental_field` follows `incremental_field` unless it is set, because a test that
    names a field usually means to sync incrementally on it. Set it to False for a full refresh on a
    schema that still has an incremental field.
    """
    return SourceInputs(
        schema_name=schema_name,
        schema_id="00000000-0000-4000-8000-000000000001",
        source_id="00000000-0000-4000-8000-000000000002",
        team_id=team_id,
        should_use_incremental_field=(
            incremental_field is not None if should_use_incremental_field is None else should_use_incremental_field
        ),
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        db_incremental_field_last_value_before_lookback=db_incremental_field_last_value_before_lookback,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        job_id=job_id,
        logger=logger if logger is not None else structlog.get_logger(_LOGGER_NAME),
        reset_pipeline=reset_pipeline,
        api_version=api_version,
        source_cursor=source_cursor,
        history_start=history_start,
    )
