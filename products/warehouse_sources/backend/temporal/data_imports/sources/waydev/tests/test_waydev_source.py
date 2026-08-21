import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.waydev import WaydevSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source import WaydevSource


class TestWaydevSource:
    def setup_method(self) -> None:
        self.source = WaydevSource()
        self.team_id = 123
        self.config = WaydevSourceConfig(api_key="key")

    def test_api_version(self) -> None:
        assert self.source.supported_versions == ("v2",)
        assert self.source.default_version == "v2"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Waydev API token"),
            ((False, 403), False, "Could not connect to Waydev with the provided API token"),
            ((False, None), False, "Could not connect to Waydev with the provided API token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.waydev.source.validate_waydev_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, int | None],
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
