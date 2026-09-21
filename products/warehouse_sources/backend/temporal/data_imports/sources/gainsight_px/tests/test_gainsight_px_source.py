import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source import GainsightPxSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightpx import (
    GainsightPxSourceConfig,
)


class TestGainsightPxSource:
    def setup_method(self):
        self.source = GainsightPxSource()
        self.team_id = 123
        self.config = GainsightPxSourceConfig(api_key="key", region="us")

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"],
    )
    def test_non_retryable_errors_includes_auth_keys(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_every_endpoint(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_is_full_refresh(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        # No Gainsight PX list endpoint exposes a server-side "updated since" filter, so every
        # table must be full refresh — advertising incremental would silently corrupt the cursor.
        assert schema.supports_incremental is False
        assert schema.supports_append is False

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_advertises_a_primary_key(self, endpoint):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.detected_primary_keys

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users"])
        assert len(schemas) == 1
        assert schemas[0].name == "users"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_lists_tables_without_credentials(self):
        # A static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        # Canonical descriptions should flow into the documented catalog.
        users = next(t for t in tables if t["name"] == "users")
        assert users["description"]
        assert users["sync_methods"] == ["Full refresh"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.source.validate_gainsight_px_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)
