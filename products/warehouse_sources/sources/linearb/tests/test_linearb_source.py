import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message"),
        [
            (200, True, None),
        ],
    )
    def test_validate_credentials(
        self,
        status_code: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert len(network.requests_log) == 1
        assert network.requests_log[0].headers["x-api-key"] == "test-key"
