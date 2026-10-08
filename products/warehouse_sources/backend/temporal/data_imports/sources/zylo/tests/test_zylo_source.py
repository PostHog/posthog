import pytest
from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zylo import ZyloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source import ZyloSource


class TestZyloSource:
    def setup_method(self) -> None:
        self.source = ZyloSource()
        self.team_id = 123
        self.config = ZyloSourceConfig(token_id="tok_id", token_secret="tok_secret")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Applications"])
        assert len(schemas) == 1
        assert schemas[0].name == "Applications"

    @pytest.mark.parametrize(
        ("mock_return", "expected_valid", "expected_message"),
        [
            (True, True, None),
            (False, False, "Invalid Zylo credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.validate_zylo_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: MagicMock, mock_return: bool, expected_valid: bool, expected_message: str | None
    ) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("tok_id", "tok_secret")

    @pytest.mark.parametrize(
        "config",
        [
            ZyloSourceConfig(token_id="", token_secret="tok_secret"),
            ZyloSourceConfig(token_id="tok_id", token_secret=""),
        ],
    )
    def test_validate_credentials_requires_both_fields(self, config: ZyloSourceConfig) -> None:
        is_valid, error_message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert error_message == "Zylo token ID and token secret are required"

    @pytest.mark.parametrize(
        ("status", "expected_message"),
        [
            (200, None),
            (429, None),
            (500, None),
            (401, "API key is invalid"),
            (403, "API key is missing the `applications:read and spend:read` permission scope"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zylo.source.probe_endpoint_status")
    def test_get_endpoint_permissions(
        self, mock_probe: MagicMock, status: int | None, expected_message: str | None
    ) -> None:
        mock_probe.return_value = status

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["PurchaseOrders"])

        assert permissions == {"PurchaseOrders": expected_message}

    def test_get_endpoint_permissions_unknown_endpoint_is_reachable(self) -> None:
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["NotARealEndpoint"])
        assert permissions == {"NotARealEndpoint": None}
