from typing import Any

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.plausible import PlausibleResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    ENDPOINTS,
    PLAUSIBLE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.source import PlausibleSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.plausible.source"


def _config(host: str | None = None) -> mock.MagicMock:
    config = mock.MagicMock()
    config.api_key = "key"
    config.site_id = "example.com"
    config.host = host
    return config


def _inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = "timeseries"
    inputs.team_id = 1
    inputs.should_use_incremental_field = False
    inputs.db_incremental_field_last_value = None
    for key, value in overrides.items():
        setattr(inputs, key, value)
    return inputs


class TestSourceConfig:
    def test_source_type(self):
        assert PlausibleSource().source_type == ExternalDataSourceType.PLAUSIBLE

    def test_get_source_config_fields(self):
        config = PlausibleSource().get_source_config

        assert config.label == "Plausible"
        field_names = {field.name for field in config.fields}
        assert field_names == {"api_key", "site_id", "host"}

        by_name = {field.name: field for field in config.fields}
        assert all(isinstance(field, SourceFieldInputConfig) for field in by_name.values())
        api_key, site_id, host = by_name["api_key"], by_name["site_id"], by_name["host"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(site_id, SourceFieldInputConfig)
        assert isinstance(host, SourceFieldInputConfig)
        assert api_key.required is True
        assert api_key.secret is True
        assert site_id.required is True
        # Host is optional so Plausible Cloud users can leave it blank.
        assert host.required is False

    def test_connection_host_fields(self):
        # The API key is sent to `host`, so retargeting it must re-require secrets.
        assert PlausibleSource().connection_host_fields == ["host"]

    def test_non_retryable_errors_cover_auth(self):
        errors = PlausibleSource().get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors


class TestGetSchemas:
    def test_all_endpoints_present_and_incremental(self):
        schemas = PlausibleSource().get_schemas(_config(), team_id=1)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is True
            assert [f["field"] for f in schema.incremental_fields] == ["date"]

    def test_names_filter(self):
        schemas = PlausibleSource().get_schemas(_config(), team_id=1, names=["sources", "pages"])
        assert {s.name for s in schemas} == {"sources", "pages"}


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.validate_plausible_credentials")
    def test_valid(self, mock_validate):
        mock_validate.return_value = (True, None)
        source = PlausibleSource()
        with mock.patch.object(source, "is_database_host_valid", return_value=(True, None)):
            assert source.validate_credentials(_config(), team_id=1) == (True, None)

    @mock.patch(f"{_MODULE}.validate_plausible_credentials")
    def test_invalid_credentials_surface_message(self, mock_validate):
        mock_validate.return_value = (False, "Plausible rejected the API key.")
        source = PlausibleSource()
        with mock.patch.object(source, "is_database_host_valid", return_value=(True, None)):
            ok, error = source.validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "Plausible rejected the API key."

    def test_unsafe_host_blocked(self):
        source = PlausibleSource()
        with mock.patch.object(source, "is_database_host_valid", return_value=(False, "Host not allowed")):
            ok, error = source.validate_credentials(_config(host="http://10.0.0.1"), team_id=1)
        assert ok is False
        assert error == "Host not allowed"


class TestResumableAndPipeline:
    def test_get_resumable_source_manager_bound_to_data_class(self):
        manager = PlausibleSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PlausibleResumeConfig

    @mock.patch(f"{_MODULE}.plausible_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_plausible_source):
        source = PlausibleSource()
        manager = mock.MagicMock()
        inputs = _inputs(should_use_incremental_field=True, db_incremental_field_last_value="2024-06-01")

        with mock.patch.object(source, "is_database_host_valid", return_value=(True, None)):
            source.source_for_pipeline(_config(), manager, inputs)

        kwargs = mock_plausible_source.call_args.kwargs
        assert kwargs["site_id"] == "example.com"
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "timeseries"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01"

    @mock.patch(f"{_MODULE}.plausible_source")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_plausible_source):
        source = PlausibleSource()
        with mock.patch.object(source, "is_database_host_valid", return_value=(False, "Host not allowed")):
            with pytest.raises(ValueError, match="Host not allowed"):
                source.source_for_pipeline(_config(host="http://10.0.0.1"), mock.MagicMock(), _inputs())


class TestCanonicalDescriptions:
    def test_descriptions_keyed_by_endpoint_names(self):
        descriptions = PlausibleSource().get_canonical_descriptions()
        # Every endpoint should have a curated description.
        assert set(descriptions.keys()) == set(PLAUSIBLE_ENDPOINTS.keys())
        for entry in descriptions.values():
            assert entry.get("description")
            assert "date" in entry.get("columns", {})
