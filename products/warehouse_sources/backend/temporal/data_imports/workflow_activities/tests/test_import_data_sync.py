import uuid
import contextlib
from datetime import datetime

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import import_data_sync as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    _handle_import_error,
    _is_transient_transport_error,
    import_data_activity_sync,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class _FakeAsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _passthrough(fn):
    """Stand-in for database_sync_to_async_pool that just calls the wrapped fn."""

    async def _inner(*args, **kwargs):
        return fn(*args, **kwargs)

    return _inner


@contextlib.contextmanager
def _patched_activity(source_mock):
    """Patch out every dependency import_data_activity_sync touches before source setup."""
    model = mock.MagicMock()
    model.pipeline.source_type = "MongoDB"
    model.pipeline.job_inputs = {}
    model.folder_path = mock.Mock(return_value="dataset")

    schema = mock.MagicMock()
    schema.should_use_incremental_field = False
    schema.row_filters = None

    with (
        mock.patch.object(module, "tag_queries"),
        mock.patch.object(module, "report_heartbeat_timeout"),
        mock.patch.object(module, "Heartbeater", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "ShutdownMonitor", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "setup_row_tracking", new=mock.AsyncMock()),
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(return_value=model)),
        mock.patch.object(module, "_get_external_data_schema", new=mock.AsyncMock(return_value=schema)),
        mock.patch.object(module, "ExternalDataSourceType", return_value="MongoDB"),
        mock.patch.object(module, "bind_job_context"),
        mock.patch.object(module, "trim_source_job_inputs", new=mock.AsyncMock()),
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
    ):
        yield handle_mock


def _make_source(error: Exception, non_retryable: dict[str, str | None]):
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.get_non_retryable_errors.return_value = non_retryable
    source.source_for_pipeline.side_effect = error
    return source


def _inputs() -> ImportDataActivityInputs:
    return ImportDataActivityInputs(
        team_id=1,
        schema_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        run_id=str(uuid.uuid4()),
        reset_pipeline=True,
    )


@pytest.mark.asyncio
async def test_non_retryable_setup_error_routes_through_handler():
    # A MongoDB mongodb+srv:// URI resolves DNS in the MongoClient constructor, so a deleted
    # cluster hostname raises during source setup (source_for_pipeline), before the run phase.
    error = Exception("The DNS query name does not exist: _mongodb._tcp.cluster0.example.mongodb.net.")
    source = _make_source(error, {"The DNS query name does not exist": None})

    with _patched_activity(source) as handle_mock:
        # handle_non_retryable_error always raises (re-raises the error, or NonRetryableException
        # once retries are exhausted) — mirror that so the activity doesn't fall through to _run.
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args.args[3] is error


@pytest.mark.asyncio
async def test_retryable_setup_error_is_reraised():
    error = Exception("connection reset by peer")
    source = _make_source(error, {"The DNS query name does not exist": None})

    with _patched_activity(source) as handle_mock:
        with pytest.raises(Exception, match="connection reset by peer"):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_config_routes_through_handler():
    # A corrupt / double-encoded stored config makes parse_config raise deterministically before
    # source setup. It must be treated as non-retryable instead of crash-looping on every attempt.
    error = ValueError("invalid literal for int() with base 10: 'not-an-int'")
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.side_effect = error
    source.get_non_retryable_errors.return_value = {}

    with _patched_activity(source) as handle_mock:
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args.args[3] is error
    source.source_for_pipeline.assert_not_called()


def _incremental_schema(*, is_incremental: bool, lookback_seconds: int | None) -> mock.MagicMock:
    schema = mock.MagicMock()
    schema.should_use_incremental_field = True
    schema.is_incremental = is_incremental
    schema.incremental_field_type = IncrementalFieldType.Timestamp
    schema.incremental_field_lookback_seconds = lookback_seconds
    schema.incremental_field_earliest_value = None
    schema.row_filters = None
    schema.sync_type_config = {
        "incremental_field_last_value": "2026-06-14T15:33:31.802833",
        "incremental_field_type": "timestamp",
    }
    return schema


@contextlib.contextmanager
def _patched_activity_reaching_run(source_mock, schema):
    model = mock.MagicMock()
    model.pipeline.source_type = "MongoDB"
    model.pipeline.job_inputs = {}
    model.folder_path = mock.Mock(return_value="dataset")

    with (
        mock.patch.object(module, "tag_queries"),
        mock.patch.object(module, "report_heartbeat_timeout"),
        mock.patch.object(module, "Heartbeater", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "ShutdownMonitor", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "setup_row_tracking", new=mock.AsyncMock()),
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(return_value=model)),
        mock.patch.object(module, "_get_external_data_schema", new=mock.AsyncMock(return_value=schema)),
        mock.patch.object(module, "ExternalDataSourceType", return_value="MongoDB"),
        mock.patch.object(module, "bind_job_context"),
        mock.patch.object(module, "trim_source_job_inputs", new=mock.AsyncMock()),
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "_run", new=mock.AsyncMock(return_value=mock.sentinel.run_result)),
    ):
        yield


def _inputs_no_reset() -> ImportDataActivityInputs:
    return ImportDataActivityInputs(
        team_id=1,
        schema_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        run_id=str(uuid.uuid4()),
        reset_pipeline=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_incremental,expected_last_value",
    [
        (True, datetime(2026, 6, 14, 14, 33, 31, 802833)),
        (False, datetime(2026, 6, 14, 15, 33, 31, 802833)),
    ],
)
async def test_incremental_lookback_shifts_query_value_not_stored_watermark(is_incremental, expected_last_value):
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.source_for_pipeline.return_value = mock.MagicMock()
    schema = _incremental_schema(is_incremental=is_incremental, lookback_seconds=3600)

    with _patched_activity_reaching_run(source, schema):
        await import_data_activity_sync(_inputs_no_reset())

    _, source_inputs = source.source_for_pipeline.call_args.args
    assert source_inputs.db_incremental_field_last_value == expected_last_value
    assert schema.sync_type_config["incremental_field_last_value"] == "2026-06-14T15:33:31.802833"


def _proxy_error_wrapping_timeout() -> Exception:
    # The exact shape from the signal: a proxy-connect TimeoutError surfaced as a requests ProxyError.
    err = requests.exceptions.ProxyError("Cannot connect to proxy")
    err.__cause__ = TimeoutError("timed out")
    return err


def _generic_error_wrapping_connection_reset() -> Exception:
    err = Exception("something went wrong")
    err.__cause__ = ConnectionResetError("connection reset by peer")
    return err


@pytest.mark.parametrize(
    "error,expected",
    [
        (_proxy_error_wrapping_timeout(), True),
        (requests.exceptions.ConnectionError("connection aborted"), True),
        (requests.exceptions.ReadTimeout("read timed out"), True),
        (ConnectionResetError("connection reset by peer"), True),
        (_generic_error_wrapping_connection_reset(), True),
        # A message that merely mentions a network phrase is not a transport exception — stays loud.
        (Exception("connection reset by peer"), False),
        (ValueError("Invalid credentials"), False),
    ],
)
def test_is_transient_transport_error(error, expected):
    assert _is_transient_transport_error(error) is expected


def _mock_logger() -> mock.MagicMock:
    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()
    return logger


@pytest.mark.asyncio
async def test_handle_import_error_logs_transient_transport_error_as_warning():
    # Transient transport blips are re-raised for Temporal to retry but must not mint an
    # error-tracking issue, so they log at warning rather than exception.
    error = _proxy_error_wrapping_timeout()
    logger = _mock_logger()
    source = mock.MagicMock()
    source.get_non_retryable_errors.return_value = {"Invalid credentials": None}
    job_inputs = mock.MagicMock(job_type="MongoDB")

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(requests.exceptions.ProxyError):
            await _handle_import_error(job_inputs, logger, error)

    logger.awarning.assert_awaited_once()
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_import_error_logs_unclassified_error_as_exception():
    error = Exception("some unexpected failure")
    logger = _mock_logger()
    source = mock.MagicMock()
    source.get_non_retryable_errors.return_value = {"Invalid credentials": None}
    job_inputs = mock.MagicMock(job_type="MongoDB")

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(Exception, match="some unexpected failure"):
            await _handle_import_error(job_inputs, logger, error)

    logger.aexception.assert_awaited_once()
    logger.awarning.assert_not_awaited()
