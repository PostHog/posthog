from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.swarmia import (
    SwarmiaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source import SwarmiaSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.swarmia.source"


class TestSwarmiaSource:
    def setup_method(self) -> None:
        self.source = SwarmiaSource()
        self.config = SwarmiaSourceConfig(api_key="token")

    @parameterized.expand(
        [
            ("valid_token", 200, None, True),
            ("invalid_token", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_fails", 403, "investment", False),
            ("network_failure", None, None, False),
        ]
    )
    @patch(f"{_SOURCE_MODULE}.check_credentials")
    def test_validate_credentials(
        self,
        _name: str,
        status: int | None,
        schema_name: str | None,
        expected_valid: bool,
        mock_check: MagicMock,
    ) -> None:
        mock_check.return_value = status

        valid, error = self.source.validate_credentials(self.config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        if not expected_valid:
            assert error
