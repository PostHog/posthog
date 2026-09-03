import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.square import SquareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.square.settings import ENDPOINTS, SQUARE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.square.source import SquareSource

INCREMENTAL_ENDPOINTS = {"payments", "refunds"}


class TestSquareSource:
    def setup_method(self) -> None:
        self.source = SquareSource()
        self.team_id = 123
        self.config = SquareSourceConfig(access_token="EAAA-test", environment="production")

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(SQUARE_ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["payments"])
        assert len(schemas) == 1
        assert schemas[0].name == "payments"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "payments", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.square.source.validate_square_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.access_token, self.config.environment, schema_name)
