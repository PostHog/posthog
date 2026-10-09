import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.settings import (
    COMMERCETOOLS_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source import CommercetoolsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.commercetools import (
    CommercetoolsSourceConfig,
)


class TestCommercetoolsSource:
    def setup_method(self):
        self.source = CommercetoolsSource()
        self.team_id = 123
        self.config = CommercetoolsSourceConfig(
            region="us-central1.gcp",
            project_key="my-project",
            client_id="client-id",
            client_secret="client-secret",
        )

    def test_connection_host_fields_cover_region_and_project(self):
        assert self.source.connection_host_fields == ["region", "project_key"]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_canonical_descriptions_cover_every_endpoint(self, endpoint):
        # A missing entry silently falls back to LLM enrichment for the whole table.
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert COMMERCETOOLS_ENDPOINTS[endpoint].primary_key in entry["columns"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid commercetools API client credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.commercetools.source.validate_commercetools_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("us-central1.gcp", "my-project", "client-id", "client-secret")
