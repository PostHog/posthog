import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import GTM_SCHEMAS
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.source import (
    GoogleTagManagerSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> GoogleTagManagerSourceConfig:
    return GoogleTagManagerSourceConfig(account_id="123", google_tag_manager_integration_id=1)


def _http_error(status: int) -> requests.HTTPError:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    return requests.HTTPError(response=response)


def test_source_type():
    assert GoogleTagManagerSource().source_type == ExternalDataSourceType.GOOGLETAGMANAGER


def test_get_source_config_fields():
    cfg = GoogleTagManagerSource().get_source_config

    assert {field.name for field in cfg.fields} == {"google_tag_manager_integration_id", "account_id"}
    assert cfg.label == "Google Tag Manager"
    assert cfg.category == "Analytics"
    assert cfg.releaseStatus == "alpha"
    assert cfg.featureFlag is None


def test_version_metadata():
    src = GoogleTagManagerSource()
    assert src.supported_versions == ("v2",)
    assert src.default_version == "v2"
    assert src.api_docs_url.startswith("https://")


def test_get_schemas_returns_all_schemas_as_snapshots():
    schemas = GoogleTagManagerSource().get_schemas(_config(), team_id=1)

    assert {s.name for s in schemas} == set(GTM_SCHEMAS.keys())
    # Tag Manager has no server-side timestamp filter, so every table is a full-refresh snapshot.
    for schema in schemas:
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []


def test_get_schemas_filters_by_names():
    schemas = GoogleTagManagerSource().get_schemas(_config(), team_id=1, names=["tags", "triggers"])

    assert {s.name for s in schemas} == {"tags", "triggers"}


def test_canonical_descriptions_cover_every_schema():
    # A stale canonical file (missing a table, or naming one that no longer exists) silently drops
    # curated docs, so keep it in lockstep with the schema catalog.
    assert set(CANONICAL_DESCRIPTIONS.keys()) == set(GTM_SCHEMAS.keys())


def test_get_oauth_accounts_maps_accounts():
    accounts = [
        {"accountId": "123", "name": "Acme", "path": "accounts/123"},
        {"accountId": "456", "name": "", "path": "accounts/456"},
        {"path": "accounts/789"},  # no accountId — skipped
    ]
    with (
        mock.patch.object(source_module, "google_tag_manager_session"),
        mock.patch.object(source_module, "list_accounts", return_value=accounts),
    ):
        result = GoogleTagManagerSource().get_oauth_accounts(integration_id=1, team_id=1)

    assert [(a.value, a.display_name) for a in result] == [("123", "Acme"), ("456", "456")]


def test_validate_credentials_success():
    with (
        mock.patch.object(source_module, "google_tag_manager_session"),
        mock.patch.object(source_module, "list_accounts", return_value=[{"accountId": "123"}]),
    ):
        ok, error = GoogleTagManagerSource().validate_credentials(_config(), team_id=1)

    assert ok is True
    assert error is None


def test_validate_credentials_account_not_visible():
    with (
        mock.patch.object(source_module, "google_tag_manager_session"),
        mock.patch.object(source_module, "list_accounts", return_value=[{"accountId": "999"}]),
    ):
        ok, error = GoogleTagManagerSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "123" in error


@pytest.mark.parametrize("status", [401, 403])
def test_validate_credentials_rejects_bad_auth(status):
    with (
        mock.patch.object(source_module, "google_tag_manager_session"),
        mock.patch.object(source_module, "list_accounts", side_effect=_http_error(status)),
    ):
        ok, error = GoogleTagManagerSource().validate_credentials(_config(), team_id=1)

    assert ok is False
    assert "reconnect" in error.lower()


def test_source_for_pipeline_plumbs_args():
    inputs = SourceInputs(
        schema_name="tags",
        schema_id="s",
        source_id="src",
        team_id=7,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="j",
        logger=mock.Mock(),
        reset_pipeline=False,
    )
    with mock.patch.object(source_module, "google_tag_manager_source", return_value="response") as mocked:
        result = GoogleTagManagerSource().source_for_pipeline(_config(), inputs)

    assert result == "response"
    _, kwargs = mocked.call_args
    assert kwargs["resource_name"] == "tags"
    assert kwargs["team_id"] == 7


def test_get_non_retryable_errors_covers_auth_failures():
    errors = GoogleTagManagerSource().get_non_retryable_errors()

    assert "401 Client Error" in errors
    assert "403 Client Error" in errors
    assert "invalid_grant" in errors
