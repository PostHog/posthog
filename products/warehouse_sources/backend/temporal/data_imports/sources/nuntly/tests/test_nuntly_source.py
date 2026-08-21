from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source import NuntlySource


class TestNuntlySource:
    def setup_method(self) -> None:
        self.source = NuntlySource()
        self.team_id = 123
        self.config = NuntlySourceConfig(api_key="apk_test")

    @parameterized.expand(
        [
            (True, True, None),
            (False, False, "Invalid credentials"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source.validate_nuntly_credentials"
    )
    def test_validate_credentials(
        self, probe_valid: bool, expected_valid: bool, expected_message: str | None, mock_validate: mock.Mock
    ) -> None:
        mock_validate.return_value = (probe_valid, 200 if probe_valid else 401)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("apk_test")
