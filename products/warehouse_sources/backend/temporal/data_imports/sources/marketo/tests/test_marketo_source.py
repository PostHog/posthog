import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketo import (
    MarketoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import MARKETO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source import MarketoSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.validate_marketo_credentials"
)
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source.marketo_source"

INCREMENTAL_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if c.incremental_field)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in MARKETO_ENDPOINTS.items() if not c.incremental_field)


class TestMarketoSource:
    def setup_method(self) -> None:
        self.source = MarketoSource()
        self.team_id = 123
        self.config = MarketoSourceConfig(
            munchkin_id="123-ABC-456",
            client_id="client-id",
            client_secret="client-secret",
            start_date="2024-01-01",
        )

    @pytest.mark.parametrize(
        "error_key",
        ["Marketo authentication failed", "Marketo API error 601", "Marketo API error 603", "Marketo API error 607"],
    )
    def test_permanent_failures_disable_the_source_instead_of_retrying(self, error_key: str) -> None:
        errors = self.source.get_non_retryable_errors()

        assert errors[error_key]
