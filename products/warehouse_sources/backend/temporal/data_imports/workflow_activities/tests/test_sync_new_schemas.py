import contextlib

import pytest
from unittest import mock

from posthog.models.integration import UndecryptedIntegrationSecretError
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_schema import SchemaSyncResult
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import sync_new_schemas as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(source_mock, schemas_created=None, source_api_version=None):
    """Patch DB + registry so the activity runs without a database or real source."""
    existing_source = mock.MagicMock(
        source_type="GoogleAds", job_inputs={"k": "v"}, deleted=False, api_version=source_api_version
    )
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


def _run_activity(source_mock, schemas_created=None, source_api_version=None):
    patches = _patch_common(source_mock, schemas_created, source_api_version=source_api_version)
    with contextlib.ExitStack() as stack:
        entered = {name: stack.enter_context(patcher) for name, patcher in patches.items()}
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))
    return entered


@pytest.mark.parametrize(
    "error_msg,non_retryable,expected_exc",
    [
        (
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            {"invalid_grant": None},
            None,
        ),
        (
            "UNAVAILABLE: transient network blip",
            {"invalid_grant": None},
            "transient network blip",
        ),
    ],
    ids=["non_retryable_error_is_skipped", "unknown_error_propagates"],
)
def test_get_schemas_error_handling(error_msg, non_retryable, expected_exc):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = non_retryable

    if expected_exc is None:
        _run_activity(source_mock)
    else:
        with pytest.raises(Exception, match=expected_exc):
            _run_activity(source_mock)


@pytest.mark.parametrize(
    "error_msg",
    [
        "Could not connect to ClickHouse at https://example.invalid:8443: "
        "('Cannot connect to proxy.', TimeoutError('timed out'))",
        "Could not connect to ClickHouse at https://example.invalid:8443: Tunnel connection failed: 502 Bad Gateway",
    ],
    ids=["proxy_connect_timeout", "proxy_tunnel_gateway_status"],
)
def test_transient_egress_proxy_error_is_not_reported(error_msg):
    # Discovery only consults get_non_retryable_errors, so a source that lists the proxy fragments
    # as retryable is still unprotected here. The marker type is the only thing that keeps the blip
    # out of error tracking, and raising it leaves the Temporal retry intact.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}

    with pytest.raises(NonReportableError) as exc_info:
        _run_activity(source_mock)

    assert str(exc_info.value) == error_msg


def test_proxy_auth_failure_is_still_reported():
    # A 407 wraps the same "Cannot connect to proxy." prefix but answers every attempt the same
    # way, so it must stay reportable.
    error_msg = (
        "Could not connect to ClickHouse at https://example.invalid:8443: "
        "('Cannot connect to proxy.', OSError('Tunnel connection failed: 407 Proxy Authentication Required'))"
    )
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}

    with pytest.raises(Exception) as exc_info:
        _run_activity(source_mock)

    assert not isinstance(exc_info.value, NonReportableError)


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
