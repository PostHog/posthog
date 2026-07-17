import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import sync_new_schemas as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(source_mock, source_api_version="v1"):
    """Patch DB + registry so the activity runs without a database or real source."""
    existing_source = mock.MagicMock(
        source_type="GoogleAds", job_inputs={"k": "v"}, deleted=False, api_version=source_api_version
    )
    objects = mock.MagicMock()
    objects.filter.return_value.exclude.return_value.exists.return_value = True
    objects.get.return_value = existing_source

    return (
        mock.patch.object(module, "close_old_connections"),
        mock.patch.object(module.ExternalDataSource, "objects", objects),
        mock.patch.object(module, "ExternalDataSourceType", return_value="GoogleAds"),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "sync_old_schemas_with_new_schemas", return_value=([], [])),
    )


def _run_activity(source_mock, supported_versions=("v1",), source_api_version="v1"):
    source_mock.supported_versions = supported_versions
    patches = _patch_common(source_mock, source_api_version)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))


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
    "supported_versions, threads_pin",
    [(("v1",), False), (("v23", "v24"), True)],
    ids=["single_version_does_not_thread", "multi_version_threads_pin"],
)
def test_discovery_threads_pin_only_for_multi_version_sources(supported_versions, threads_pin):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {"cfg": True}
    source_mock.get_schemas.return_value = []

    _run_activity(source_mock, supported_versions=supported_versions, source_api_version="v23")

    if threads_pin:
        source_mock.get_schemas.assert_called_once_with({"cfg": True}, 1, api_version="v23")
    else:
        source_mock.get_schemas.assert_called_once_with({"cfg": True}, 1)


def test_unparseable_config_is_skipped():
    source_mock = mock.MagicMock()
    source_mock.parse_config.side_effect = TypeError("Cannot build 'MySQLSourceConfig' from str; expected a mapping")

    _run_activity(source_mock)

    source_mock.get_schemas.assert_not_called()
