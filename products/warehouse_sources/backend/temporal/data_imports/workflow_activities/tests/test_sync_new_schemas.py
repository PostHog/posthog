import contextlib

import pytest
from unittest import mock

from django.db import OperationalError

from posthog.models.integration import UndecryptedIntegrationSecretError
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_schema import SchemaSyncResult
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import sync_new_schemas as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(source_mock, schemas_created=None, source_api_version=None, merge_error=None):
    """Patch DB + registry so the activity runs without a database or real source."""
    existing_source = mock.MagicMock(
        source_type="GoogleAds", job_inputs={"k": "v"}, deleted=False, api_version=source_api_version
    )
    existing_source.merge_connection_metadata.side_effect = merge_error
    objects = mock.MagicMock()
    objects.filter.return_value.exclude.return_value.exists.return_value = True
    objects.get.return_value = existing_source

    return {
        "close_old_connections": mock.patch.object(module, "close_old_connections"),
        "objects": mock.patch.object(module.ExternalDataSource, "objects", objects),
        "source_type": mock.patch.object(module, "ExternalDataSourceType", return_value="GoogleAds"),
        "is_registered": mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        "get_source": mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        "sync_old_schemas_with_new_schemas": mock.patch.object(
            module,
            "sync_old_schemas_with_new_schemas",
            return_value=SchemaSyncResult(created=schemas_created or [], deleted=[]),
        ),
        "auto_enable_new_schemas": mock.patch.object(module, "auto_enable_new_schemas", return_value=[]),
    }


def _run_activity(source_mock, schemas_created=None, source_api_version=None, merge_error=None):
    patches = _patch_common(
        source_mock, schemas_created, source_api_version=source_api_version, merge_error=merge_error
    )
    with contextlib.ExitStack() as stack:
        entered = {name: stack.enter_context(patcher) for name, patcher in patches.items()}
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))
    return entered


@pytest.mark.parametrize(
    "error_msg,non_retryable,retryable,expected_exc",
    [
        (
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            {"invalid_grant": None},
            set(),
            None,
        ),
        (
            "UNAVAILABLE: transient network blip",
            {"invalid_grant": None},
            set(),
            "transient network blip",
        ),
    ],
    ids=["non_retryable_error_is_skipped", "unknown_error_propagates"],
)
def test_get_schemas_error_handling(error_msg, non_retryable, retryable, expected_exc):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = non_retryable
    source_mock.get_retryable_errors.return_value = retryable

    if expected_exc is None:
        _run_activity(source_mock)
    else:
        with pytest.raises(Exception, match=expected_exc):
            _run_activity(source_mock)


def test_retryable_error_is_reraised_for_temporal_retry():
    # A retryable source error (a transient connect blip) must fail the activity as NonReportableError,
    # not complete it. NonReportableError keeps the workflow's Temporal retry (the activity interceptor
    # re-raises it without capturing), so discovery retries within the run instead of skipping the whole
    # ~6h pass. Mirrors import_data_sync's handling of the same get_retryable_errors set.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception("250001: Could not connect to Snowflake backend after 3 attempt(s)")
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = {"Could not connect to Snowflake backend after"}

    with pytest.raises(NonReportableError):
        _run_activity(source_mock)


@pytest.mark.parametrize(
    "error_msg",
    [
        "HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: /v1/things "
        "(Caused by ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 429 Too Many Requests')))",
        "Could not connect to ClickHouse at https://example.invalid:8443: ('Cannot connect to proxy.', TimeoutError('timed out'))",
    ],
    ids=["tunnel_429", "proxy_connect_timeout"],
)
def test_transient_egress_proxy_error_is_reraised_without_source_opt_in(error_msg):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = set()

    with pytest.raises(NonReportableError) as exc_info:
        _run_activity(source_mock)

    assert str(exc_info.value) == error_msg


def test_proxy_auth_failure_is_still_reported():
    error_msg = (
        "Could not connect to ClickHouse at https://example.invalid:8443: "
        "('Cannot connect to proxy.', OSError('Tunnel connection failed: 407 Proxy Authentication Required'))"
    )
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = set()

    with pytest.raises(Exception, match="407") as exc_info:
        _run_activity(source_mock)

    assert not isinstance(exc_info.value, NonReportableError)


def test_all_source_non_retryable_error_is_skipped():
    # "Database host not allowed" (and the rest of Any_Source_Errors) is raised from shared
    # connection code, not any one source, so it's never in a source's own
    # get_non_retryable_errors. Without merging it in here, discovery retries forever and spams
    # error tracking on a host that will never resolve.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception("Database host not allowed: could not resolve host")
    source_mock.get_non_retryable_errors.return_value = {}

    _run_activity(source_mock)


def test_undecrypted_integration_secret_error_is_skipped():
    # Checked by type, not message, so it must be skipped even when get_non_retryable_errors
    # has no matching entry — otherwise discovery retries forever on an unrecoverable decryption
    # failure and spams error tracking every cycle.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = UndecryptedIntegrationSecretError()
    source_mock.get_non_retryable_errors.return_value = {}

    _run_activity(source_mock)


def test_discovery_uses_source_pinned_api_version():
    # A pinned source must discover schemas under its pin, not the default — dropping the pin
    # here makes discovery reconcile under the wrong vendor version (tables vanish/duplicate).
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.resolve_api_version.side_effect = lambda pinned: pinned or "v-default"

    _run_activity(source_mock, source_api_version="v-old")

    assert source_mock.get_schemas.call_args.kwargs["api_version"] == "v-old"


def test_unparseable_config_is_skipped():
    source_mock = mock.MagicMock()
    source_mock.parse_config.side_effect = TypeError("Cannot build 'MySQLSourceConfig' from str; expected a mapping")

    _run_activity(source_mock)

    source_mock.get_schemas.assert_not_called()


def test_created_schemas_are_passed_to_auto_enable():
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    discovered = mock.MagicMock()
    discovered.name = "raw_events"
    source_mock.get_schemas.return_value = [discovered]

    mocks = _run_activity(source_mock, schemas_created=["raw_events"])

    auto_enable = mocks["auto_enable_new_schemas"]
    auto_enable.assert_called_once()
    source_arg, created_arg, source_schemas_arg = auto_enable.call_args.args
    assert source_arg is mocks["objects"].get.return_value
    assert created_arg == ["raw_events"]
    assert source_schemas_arg == {"raw_events": discovered}


def test_auto_enable_not_called_when_nothing_created():
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []

    mocks = _run_activity(source_mock)

    mocks["auto_enable_new_schemas"].assert_not_called()


def test_probed_metadata_goes_through_the_locked_merge():
    # `source` is read before schema discovery, which is itself a network call, so the write has to
    # re-read the row. Assigning the field here would drop a write that landed in between.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.get_server_metadata.return_value = {"engine": "mongodb", "wire_version": 7}

    mocks = _run_activity(source_mock)

    source = mocks["objects"].get.return_value
    source.merge_connection_metadata.assert_called_once_with({"engine": "mongodb", "wire_version": 7})
    source.save.assert_not_called()


@pytest.mark.parametrize(
    "probe_error,merge_error,expected_merge_calls",
    [
        (Exception("connection refused"), None, 0),
        (None, OperationalError("canceling statement due to lock timeout"), 1),
    ],
    ids=["the_probe_fails", "the_locked_merge_fails"],
)
def test_a_failed_metadata_write_leaves_discovery_successful(probe_error, merge_error, expected_merge_calls):
    # Recording the version is incidental to discovery, and each step fails on its own terms: the
    # probe reaches an unreachable server, and the merge waits on a row lock the backfill command can
    # hold. Either one escaping would fail every discovery pass for that source, and the schemas
    # found just above would never reconcile.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.get_server_metadata.return_value = {"engine": "mongodb", "wire_version": 7}
    source_mock.get_server_metadata.side_effect = probe_error

    mocks = _run_activity(source_mock, merge_error=merge_error)

    mocks["sync_old_schemas_with_new_schemas"].assert_called_once()
    assert mocks["objects"].get.return_value.merge_connection_metadata.call_count == expected_merge_calls
