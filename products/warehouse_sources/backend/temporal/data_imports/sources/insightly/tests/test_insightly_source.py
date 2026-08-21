import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.insightly import (
    InsightlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import INSIGHTLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source import InsightlySource

# Derived from settings so a new endpoint is automatically covered by the parametrized tests below.
INCREMENTAL_ENDPOINTS = {name for name, cfg in INSIGHTLY_ENDPOINTS.items() if cfg.supports_incremental}
FULL_REFRESH_ENDPOINTS = {name for name, cfg in INSIGHTLY_ENDPOINTS.items() if not cfg.supports_incremental}


class TestInsightlySource:
    def setup_method(self) -> None:
        self.source = InsightlySource()
        self.team_id = 123
        self.config = InsightlySourceConfig(pod="na1", api_key="key")

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "Contacts", True),
            (403, None, True),  # missing scope tolerated at source-create
            (403, "Leads", False),  # but rejected for a specific schema
            (401, None, False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.validate_insightly_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        mock_validate.return_value = status
        ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert ok is expected_ok

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source.validate_insightly_credentials"
    )
    def test_validate_credentials_rejects_invalid_pod(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.side_effect = ValueError("Invalid Insightly pod/instance: 'evil.com'")
        ok, message = self.source.validate_credentials(
            InsightlySourceConfig(pod="evil.com", api_key="key"), self.team_id
        )
        assert ok is False
        assert "Invalid Insightly pod" in (message or "")
