import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohocrm import (
    ZohoCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import ZOHO_CRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source import ZohoCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    REFRESH_TOKEN_REJECTED_MESSAGE,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source"

INCREMENTAL_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if config.incremental)
FULL_REFRESH_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if not config.incremental)


class TestZohoCRMSource:
    def setup_method(self) -> None:
        self.source = ZohoCRMSource()
        self.team_id = 123
        self.config = ZohoCRMSourceConfig(region="eu", client_id="cid", client_secret="secret", refresh_token="refresh")

    def test_api_version_is_pinned_to_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v8",)
        assert self.source.default_version == "v8"
        assert self.source.api_docs_url.startswith("https://")

    @mock.patch(f"{_SOURCE_MODULE}.validate_zoho_crm_credentials")
    def test_validate_credentials_passes_the_resolved_version(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.kwargs == {
            "region": "eu",
            "client_id": "cid",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "api_version": "v8",
        }

    @pytest.mark.parametrize(
        "probe_result, expected",
        [
            ((False, REFRESH_TOKEN_REJECTED_MESSAGE), REFRESH_TOKEN_REJECTED_MESSAGE),
            ((False, None), "Invalid Zoho CRM credentials"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_zoho_crm_credentials")
    def test_validate_credentials_surfaces_a_reason(
        self, mock_validate: mock.MagicMock, probe_result: tuple[bool, str | None], expected: str
    ) -> None:
        mock_validate.return_value = probe_result

        assert self.source.validate_credentials(self.config, self.team_id) == (False, expected)
