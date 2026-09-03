import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source import EverhourSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.everhour import (
    EverhourSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.everhour.source"


class TestEverhourSource:
    def setup_method(self) -> None:
        self.source = EverhourSource()
        self.team_id = 123
        self.config = EverhourSourceConfig(api_key="ev_abc")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.everhour.com/clients?limit=100",
            "403 Client Error: Forbidden for url: https://api.everhour.com/time-records?from=2026-01-01",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.everhour.com/projects",
            "HTTPSConnectionPool(host='api.everhour.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_only_time_records_is_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["time_records"].supports_incremental is True
        assert schemas["time_records"].supports_append is True
        assert [f["field"] for f in schemas["time_records"].incremental_fields] == ["date"]

        for name in ("clients", "projects", "users", "tasks"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["time_records"])
        assert len(schemas) == 1
        assert schemas[0].name == "time_records"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the static catalog can render in public docs.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Everhour API key"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.validate_everhour_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)
