from typing import Any

import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    ENDPOINTS,
    PLAUSIBLE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.source import PlausibleSource

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

    @pytest.mark.parametrize(
        "raised,expected_key",
        [
            # A 400 is a permanent rejection from Plausible for this site.
            ("400 Client Error: Bad Request for url: https://plausible.io/api/v2/query", "400 Client Error"),
            # A self-hosted Host that doesn't resolve via DNS is raised from source_for_pipeline's
            # host validation; retrying replays the same check, so it must stop.
            (
                "Couldn't resolve the host 'stats.example.com'. Check that it's spelled correctly "
                "and reachable from the public internet.",
                "Couldn't resolve the host",
            ),
        ],
    )
    def test_permanent_errors_are_non_retryable(self, raised: str, expected_key: str):
        # The import layer classifies an error as non-retryable when a key is a substring of
        # str(error), so match against the real message shape each path produces.
        errors = PlausibleSource().get_non_retryable_errors()
        matched = [key for key in errors if key in raised]
        assert matched == [expected_key]
        assert errors[expected_key] is not None


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
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_documented_columns_match_the_columns_the_endpoint_produces(self, endpoint):
        # These descriptions are written per endpoint while the metric set is derived, so without
        # this an endpoint can document metric columns its table never gets.
        config = PLAUSIBLE_ENDPOINTS[endpoint]
        columns = PlausibleSource().get_canonical_descriptions()[endpoint]["columns"]

        assert set(columns) == {*config.column_names, *config.metrics}
