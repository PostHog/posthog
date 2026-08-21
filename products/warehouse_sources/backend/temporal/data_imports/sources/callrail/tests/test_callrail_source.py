import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source import CallRailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.callrail import (
    CallRailSourceConfig,
)


class TestCallRailSource:
    def setup_method(self) -> None:
        self.source = CallRailSource()
        self.team_id = 123
        self.config = CallRailSourceConfig(api_key="key", account_id=None)

    def test_only_documented_filter_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only calls and form_submissions expose CallRail's server-side `start_date` filter.
        assert incremental == {"calls", "form_submissions"}

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid CallRail API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.source.validate_callrail_credentials"
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
