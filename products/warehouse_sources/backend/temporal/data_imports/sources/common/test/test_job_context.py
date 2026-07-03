from products.warehouse_sources.backend.temporal.data_imports.sources.common import job_context
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import context as http_context
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import (
    bind_job_context,
    current_job_context,
    scoped_job_context,
)


def test_http_context_shim_reexports_neutral_module():
    """The HTTP context module must re-export the neutral objects unchanged."""
    assert http_context.JobContext is job_context.JobContext
    assert http_context.bind_job_context is job_context.bind_job_context
    assert http_context.scoped_job_context is job_context.scoped_job_context
    assert http_context.current_job_context is job_context.current_job_context
    # Private names a few HTTP tests reach into.
    assert http_context._current_job_context is job_context._current_job_context
    assert http_context._BOUND_LOG_FIELD_NAMES is job_context._BOUND_LOG_FIELD_NAMES


def test_scoped_job_context_sets_and_resets():
    assert current_job_context() is None
    with scoped_job_context(
        team_id=1,
        source_type="google_ads",
        external_data_source_id="s",
        external_data_schema_id="sc",
        external_data_job_id="j",
    ) as ctx:
        assert current_job_context() is ctx
        assert ctx.team_id == 1
        assert ctx.source_type == "google_ads"
    assert current_job_context() is None


def test_bind_job_context_coerces_uuid_like_ids_to_str():
    import uuid

    source_id = uuid.uuid4()
    ctx = bind_job_context(
        team_id=7,
        source_type="bigquery",
        external_data_source_id=source_id,
        external_data_schema_id="sc",
        external_data_job_id="j",
    )
    assert ctx.external_data_source_id == str(source_id)
    assert current_job_context() is ctx
