import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.honeybadger import (
    HoneybadgerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source import HoneybadgerSource


class TestHoneybadgerSource:
    def setup_method(self) -> None:
        self.source = HoneybadgerSource()
        self.team_id = 123
        self.config = HoneybadgerSourceConfig(api_key="test-token")

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://app.honeybadger.io",
            "403 Client Error: Forbidden for url: https://app.honeybadger.io",
        ],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_names_and_sync_support(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)

        for endpoint in ("faults", "notices", "deploys"):
            assert schemas[endpoint].supports_incremental is True
            assert schemas[endpoint].supports_append is True
            assert len(schemas[endpoint].incremental_fields) > 0

        for endpoint in ("projects", "sites"):
            assert schemas[endpoint].supports_incremental is False
            assert schemas[endpoint].supports_append is False
            assert schemas[endpoint].incremental_fields == []

    def test_notices_are_opt_in_by_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Notices fan out one request per fault against a 360 req/hour quota, so they must
        # not be part of the default table selection.
        assert schemas["notices"].should_sync_default is False
        assert all(schema.should_sync_default for name, schema in schemas.items() if name != "notices")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["faults"])
        assert len(schemas) == 1
        assert schemas[0].name == "faults"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        # The public docs table catalog must build from the static endpoint list with no I/O.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Honeybadger authentication token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source.validate_honeybadger_credentials"
    )
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
