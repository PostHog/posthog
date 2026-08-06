import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools import source as source_mod
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    BingWebmasterToolsError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.source import (
    BingWebmasterToolsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _config() -> BingWebmasterToolsSourceConfig:
    return BingWebmasterToolsSourceConfig(api_key="secret-key", site_url="https://example.com")


def test_source_type():
    assert BingWebmasterToolsSource().source_type == ExternalDataSourceType.BINGWEBMASTERTOOLS


def test_get_source_config_fields():
    cfg = BingWebmasterToolsSource().get_source_config
    assert {field.name for field in cfg.fields} == {"api_key", "site_url"}
    assert cfg.label == "Microsoft (Bing Webmaster Tools)"
    # A finished source is visible and connectable — the scaffold's unreleasedSource flag is gone.
    assert cfg.unreleasedSource is None
    assert cfg.releaseStatus == "alpha"


def test_api_key_field_is_secret():
    api_key_field = next(f for f in BingWebmasterToolsSource().get_source_config.fields if f.name == "api_key")
    assert api_key_field.secret is True


def test_get_schemas_returns_all_endpoints_with_date_incremental():
    schemas = BingWebmasterToolsSource().get_schemas(_config(), team_id=1)
    assert {s.name for s in schemas} == set(ENDPOINTS.keys())
    for schema in schemas:
        assert schema.supports_incremental is True
        assert schema.supports_append is True
        assert schema.incremental_fields == [
            {
                "label": "Date",
                "field": "Date",
                "type": IncrementalFieldType.Date,
                "field_type": IncrementalFieldType.Date,
            }
        ]
        assert schema.detected_primary_keys == ENDPOINTS[schema.name]["primary_key"]


def test_get_schemas_filters_by_names():
    schemas = BingWebmasterToolsSource().get_schemas(_config(), team_id=1, names=["crawl_stats"])
    assert {s.name for s in schemas} == {"crawl_stats"}


def test_validate_credentials_success_when_site_registered():
    sites = [{"Url": "https://example.com"}, {"Url": "https://other.com"}]
    with mock.patch.object(source_mod, "bing_session", return_value=mock.Mock()):
        with mock.patch.object(source_mod, "list_user_sites", return_value=sites):
            ok, error = BingWebmasterToolsSource().validate_credentials(_config(), team_id=1)
    assert ok is True
    assert error is None


def test_validate_credentials_matches_site_case_insensitively():
    # Bing lists the property without a trailing slash; a user-entered trailing slash still matches.
    config = BingWebmasterToolsSourceConfig(api_key="k", site_url="https://Example.com/")
    with mock.patch.object(source_mod, "bing_session", return_value=mock.Mock()):
        with mock.patch.object(source_mod, "list_user_sites", return_value=[{"Url": "https://example.com"}]):
            ok, error = BingWebmasterToolsSource().validate_credentials(config, team_id=1)
    assert ok is True


def test_validate_credentials_fails_when_site_absent():
    with mock.patch.object(source_mod, "bing_session", return_value=mock.Mock()):
        with mock.patch.object(source_mod, "list_user_sites", return_value=[{"Url": "https://other.com"}]):
            ok, error = BingWebmasterToolsSource().validate_credentials(_config(), team_id=1)
    assert ok is False
    assert "not a verified site" in error


@pytest.mark.parametrize("status", [401, 403])
def test_validate_credentials_fails_on_auth_error(status):
    resp = mock.Mock(status_code=status)
    http_error = requests.HTTPError(f"{status} Client Error")
    http_error.response = resp
    with mock.patch.object(source_mod, "bing_session", return_value=mock.Mock()):
        with mock.patch.object(source_mod, "list_user_sites", side_effect=http_error):
            ok, error = BingWebmasterToolsSource().validate_credentials(_config(), team_id=1)
    assert ok is False
    assert "API key" in error


def test_validate_credentials_fails_on_api_fault_without_leaking():
    with mock.patch.object(source_mod, "bing_session", return_value=mock.Mock()):
        with mock.patch.object(
            source_mod, "list_user_sites", side_effect=BingWebmasterToolsError("raw url with apikey=secret")
        ):
            ok, error = BingWebmasterToolsSource().validate_credentials(_config(), team_id=1)
    assert ok is False
    # The generic copy is shown; the raw exception text (which can embed the key) is not.
    assert "secret" not in error


def test_get_non_retryable_errors_cover_auth():
    errors = BingWebmasterToolsSource().get_non_retryable_errors()
    assert "401 Client Error" in errors
    assert "403 Client Error" in errors


def test_source_for_pipeline_plumbs_schema_name():
    inputs = mock.Mock(schema_name="crawl_stats", team_id=7)
    with mock.patch.object(source_mod, "bing_webmaster_tools_source", return_value="response") as build:
        result = BingWebmasterToolsSource().source_for_pipeline(_config(), inputs)
    assert result == "response"
    assert build.call_args.kwargs["resource_name"] == "crawl_stats"
    assert build.call_args.kwargs["team_id"] == 7
