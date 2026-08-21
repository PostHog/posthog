import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octolens import (
    OctolensSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.source import OctolensSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.octolens.source"


class TestOctolensSource:
    def setup_method(self) -> None:
        self.source = OctolensSource()
        self.team_id = 123
        self.config = OctolensSourceConfig(api_key="octolens-key")

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid or expired Octolens API key"),
            (403, False, "boom"),
            (0, False, "boom"),
        ],
    )
    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials(
        self, mock_check: mock.MagicMock, status: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_check.return_value = (status, "boom")
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials_probes_the_resolved_api_version(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id)
        mock_check.assert_called_once_with("octolens-key", "v2")

    @mock.patch(f"{SOURCE_MODULE}.check_access")
    def test_validate_credentials_rejects_unknown_schema_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown Octolens schema 'not_a_table'"
        mock_check.assert_not_called()
