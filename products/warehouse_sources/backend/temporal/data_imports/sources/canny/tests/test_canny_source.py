import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.canny.source import CannySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canny import CannySourceConfig


class TestCannySource:
    def setup_method(self) -> None:
        self.source = CannySource()
        self.team_id = 123
        self.config = CannySourceConfig(api_key="test-key")

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Canny API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.canny.source.validate_canny_credentials"
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

    def test_default_version_is_v2(self) -> None:
        # New sources are created on the newest wire; a NULL pin resolves to it too.
        assert self.source.default_version == "v2"
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.resolve_api_version(None) == "v2"
