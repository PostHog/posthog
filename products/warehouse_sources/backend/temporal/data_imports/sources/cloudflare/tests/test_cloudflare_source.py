import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import TokenCheck
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.source import CloudflareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflare import (
    CloudflareSourceConfig,
)


class TestCloudflareSource:
    def setup_method(self):
        self.source = CloudflareSource()
        self.team_id = 123
        self.config = CloudflareSourceConfig(api_token="api-token")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["zones"])
        assert len(schemas) == 1
        assert schemas[0].name == "zones"

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_substring",
        [
            (TokenCheck(is_valid=True, status=200), True, None),
            (TokenCheck(is_valid=False, status=401), False, "Cloudflare rejected your API token."),
            (TokenCheck(is_valid=False, status=403), False, "Cloudflare rejected your API token."),
            # Cloudflare's own reason is what tells a revoked token from one this endpoint
            # structurally cannot verify, so it has to reach the person reading the wizard.
            (
                TokenCheck(is_valid=False, status=400, reason="Invalid API Token (code 1000)"),
                False,
                "Invalid API Token (code 1000)",
            ),
            (
                TokenCheck(is_valid=False, status=400, reason="Invalid request headers (code 6003)", code=6003),
                False,
                "not the Global API Key",
            ),
            (TokenCheck(is_valid=False, status=None), False, "Couldn't reach Cloudflare"),
            (TokenCheck(is_valid=False, status=500), False, "Couldn't reach Cloudflare"),
            (TokenCheck(is_valid=False, status=429), False, "Couldn't reach Cloudflare"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.source.validate_cloudflare_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_substring):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_substring is None:
            assert error_message is None
        else:
            assert error_message is not None
            assert expected_substring in error_message
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_every_endpoint_is_documented_for_semantic_enrichment(self):
        # A table with no canonical entry silently falls back to LLM-derived descriptions.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
