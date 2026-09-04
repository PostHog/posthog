import pytest
from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.close.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.close.source import CloseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.close import CloseSourceConfig

INCREMENTAL_ENDPOINTS = {"Leads", "Contacts", "Opportunities", "Activities", "Tasks"}


class TestCloseSource:
    def setup_method(self) -> None:
        self.source = CloseSource()
        self.team_id = 123
        self.config = CloseSourceConfig(api_key="api_test")

    def test_get_schemas_lists_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert len(schema.incremental_fields) >= 1
        else:
            assert schema.incremental_fields == []

    def test_opportunities_advertises_both_cursors(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "Opportunities")
        fields = {f["field"] for f in schema.incremental_fields}
        assert fields == {"date_created", "date_updated"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Leads"])
        assert len(schemas) == 1
        assert schemas[0].name == "Leads"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Close API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.close.source.validate_close_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("api_test")

    def test_validate_credentials_empty_key(self) -> None:
        is_valid, error_message = self.source.validate_credentials(CloseSourceConfig(api_key=""), self.team_id)
        assert is_valid is False
        assert error_message == "Close API key is required"

    def test_retryable_errors_match_exhausted_connection_retries(self) -> None:
        error_msg = (
            "HTTPSConnectionPool(host='api.close.com', port=443): Max retries exceeded with "
            'url: /api/v1/data/search/ (Caused by ReadTimeoutError("HTTPSConnectionPool(host='
            "'api.close.com', port=443): Read timed out. (read timeout=60)\"))"
        )
        assert any(pattern in error_msg for pattern in self.source.get_retryable_errors())
