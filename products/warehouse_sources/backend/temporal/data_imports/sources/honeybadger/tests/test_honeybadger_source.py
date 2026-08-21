import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.honeybadger import (
    HoneybadgerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.source import HoneybadgerSource


class TestHoneybadgerSource:
    def setup_method(self) -> None:
        self.source = HoneybadgerSource()
        self.team_id = 123
        self.config = HoneybadgerSourceConfig(api_key="test-token")

    def test_notices_are_opt_in_by_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Notices fan out one request per fault against a 360 req/hour quota, so they must
        # not be part of the default table selection.
        assert schemas["notices"].should_sync_default is False
        assert all(schema.should_sync_default for name, schema in schemas.items() if name != "notices")

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
