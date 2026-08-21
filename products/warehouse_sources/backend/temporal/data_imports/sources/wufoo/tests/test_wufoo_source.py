import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wufoo import WufooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source import WufooSource


class TestWufooSource:
    def setup_method(self) -> None:
        self.source = WufooSource()
        self.team_id = 123
        self.config = WufooSourceConfig(subdomain="acme", api_key="wufoo-key")

    @pytest.mark.parametrize(
        "status, expected_valid",
        [(200, True), (401, False), (403, False), (500, False), (None, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source.validate_wufoo_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, status: int | None, expected_valid: bool
    ) -> None:
        mock_validate.return_value = status
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_validate_credentials_rejects_bad_subdomain_without_probing(self) -> None:
        bad_config = WufooSourceConfig(subdomain="not a domain!", api_key="wufoo-key")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source.validate_wufoo_credentials"
        ) as mock_validate:
            is_valid, message = self.source.validate_credentials(bad_config, self.team_id)
        assert is_valid is False
        assert message == "Wufoo subdomain is invalid"
        mock_validate.assert_not_called()
