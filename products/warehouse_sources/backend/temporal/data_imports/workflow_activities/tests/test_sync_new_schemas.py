import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import sync_new_schemas as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(source_mock, source_api_version=None):
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


def _run_activity(source_mock, source_api_version=None):
    patches = _patch_common(source_mock, source_api_version=source_api_version)
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
