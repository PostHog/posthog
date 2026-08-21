from typing import Literal

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shutterstock import (
    ShutterstockAuthMethodConfig,
    ShutterstockSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source import (
    ShutterstockSource,
    _auth_from_config,
)


def _basic_config(**auth_overrides: str) -> ShutterstockSourceConfig:
    return ShutterstockSourceConfig(
        auth_method=ShutterstockAuthMethodConfig(
            selection="api_key", consumer_key="ck", consumer_secret="cs", **auth_overrides
        )
    )


class TestShutterstockSource:
    def setup_method(self) -> None:
        self.source = ShutterstockSource()
        self.team_id = 123
        self.config = _basic_config()

    def test_only_server_side_filter_endpoints_are_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        incremental = {name for name, s in schemas.items() if s.supports_incremental}
        # Only the updated feeds and license history expose Shutterstock's server-side
        # `start_date` filter.
        assert incremental == {"images_updated", "videos_updated", "image_licenses", "video_licenses"}

    @pytest.mark.parametrize(
        "selection, expected",
        [
            ("api_key", {"consumer_key": "ck", "consumer_secret": "cs", "access_token": None}),
            ("access_token", {"consumer_key": None, "consumer_secret": None, "access_token": "tok"}),
        ],
    )
    def test_auth_from_config_routes_by_selection(
        self, selection: Literal["api_key", "access_token"], expected: dict[str, str | None]
    ) -> None:
        config = ShutterstockSourceConfig(
            auth_method=ShutterstockAuthMethodConfig(
                selection=selection, consumer_key="ck", consumer_secret="cs", access_token="tok"
            )
        )
        auth = _auth_from_config(config)
        assert auth.consumer_key == expected["consumer_key"]
        assert auth.consumer_secret == expected["consumer_secret"]
        assert auth.access_token == expected["access_token"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Shutterstock credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.validate_shutterstock_credentials"
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

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.check_endpoint_access"
    )
    def test_validate_credentials_with_schema_name_reports_scope_reason(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = "needs licenses.view"

        is_valid, error_message = self.source.validate_credentials(
            self.config, self.team_id, schema_name="image_licenses"
        )

        assert is_valid is False
        assert error_message == "needs licenses.view"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shutterstock.source.check_endpoint_access"
    )
    def test_get_endpoint_permissions_probes_known_endpoints_only(self, mock_check: mock.MagicMock) -> None:
        mock_check.side_effect = lambda auth, endpoint: "blocked" if endpoint == "subscriptions" else None

        permissions = self.source.get_endpoint_permissions(
            self.config, self.team_id, ["subscriptions", "image_categories", "not_an_endpoint"]
        )

        assert permissions == {"subscriptions": "blocked", "image_categories": None, "not_an_endpoint": None}
