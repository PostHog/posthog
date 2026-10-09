import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

_LOGGER_NAME = "source_testing"


def source_inputs(
    schema_name: str,
    *,
    team_id: int = 1,
    job_id: str = "00000000-0000-4000-8000-000000000003",
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    incremental_field_type: str | None = None,
    db_incremental_field_last_value: object | None = None,
    db_incremental_field_earliest_value: object | None = None,
    reset_pipeline: bool = False,
) -> SourceInputs:
    """The `SourceInputs` the pipeline hands a source, with the fields a test varies.

    `should_use_incremental_field` follows `incremental_field` unless it is set, because a test that
    names a field always means to sync incrementally on it.
    """
    return SourceInputs(
        schema_name=schema_name,
        schema_id="00000000-0000-4000-8000-000000000001",
        source_id="00000000-0000-4000-8000-000000000002",
        team_id=team_id,
        should_use_incremental_field=should_use_incremental_field or incremental_field is not None,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=db_incremental_field_earliest_value,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        job_id=job_id,
        logger=structlog.get_logger(_LOGGER_NAME),
        reset_pipeline=reset_pipeline,
    )
