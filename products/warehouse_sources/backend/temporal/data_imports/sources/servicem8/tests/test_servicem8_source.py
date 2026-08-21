from typing import Optional

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicem8 import (
    Servicem8SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.source import Servicem8Source

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.source"


class TestServiceM8Source:
    def setup_method(self) -> None:
        self.source = Servicem8Source()
        self.team_id = 123
        self.config = Servicem8SourceConfig(api_key="sm8-key")

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid credentials"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        mock_return: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        with mock.patch(f"{SOURCE_MODULE}.validate_servicem8_credentials", return_value=mock_return) as mock_validate:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert message == expected_message
        mock_validate.assert_called_once_with("sm8-key")
