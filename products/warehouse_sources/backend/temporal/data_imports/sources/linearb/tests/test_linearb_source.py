import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linearb import (
    LinearbSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.source import LinearbSource


class TestLinearbSource:
    def setup_method(self) -> None:
        self.source = LinearbSource()
        self.team_id = 123
        self.config = LinearbSourceConfig(api_key="test-key")

    def test_non_retryable_errors_cover_forbidden(self) -> None:
        # LinearB's gateway returns 403 for any bad/missing key (there is no distinct 401).
        errors = self.source.get_non_retryable_errors()
        assert any("403 Client Error" in key for key in errors)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["teams"])
        assert [s.name for s in schemas] == ["teams"]

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid LinearB API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.linearb.source.validate_linearb_credentials"
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
        mock_validate.assert_called_once_with("test-key")
