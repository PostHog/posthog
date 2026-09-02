from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohocrm import (
    ZohoCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import ZOHO_CRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source import ZohoCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMResumeConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source"

INCREMENTAL_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if config.incremental)
FULL_REFRESH_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if not config.incremental)


def _inputs(schema_name: str = "Leads", **overrides: Any) -> mock.MagicMock:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestZohoCRMSource:
    def setup_method(self) -> None:
        self.source = ZohoCRMSource()
        self.team_id = 123
        self.config = ZohoCRMSourceConfig(region="eu", client_id="cid", client_secret="secret", refresh_token="refresh")

    def test_api_version_is_pinned_to_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v8",)
        assert self.source.default_version == "v8"
        assert self.source.api_docs_url.startswith("https://")

    def test_source_config_documents_scopes_the_requests_require(self) -> None:
        # `settings.modules.READ` is the easy one to drop, because nothing in the sync path uses it:
        # it exists only so `validate_credentials` can probe /settings/modules. Zoho answers that
        # probe with a 401 OAUTH_SCOPE_MISMATCH when the scope is missing, and the blanket
        # `except Exception` in `validate_credentials` flattens it to "Invalid Zoho CRM credentials"
        # — so leaving it out of the caption fails every setup that followed the caption exactly.
        # The caption is also the docs page: posthog.com builds /docs/cdp/sources/zoho-crm from it
        # via /api/public_source_configs, so this string is the only place the scopes are published.
        required_scopes = [
            "ZohoCRM.modules.ALL",
            "ZohoCRM.settings.fields.READ",
            "ZohoCRM.settings.modules.READ",
        ]
        caption = self.source.get_source_config.caption
        forbidden_message = self.source.get_non_retryable_errors()["403 Client Error: Forbidden for url"]

        assert caption is not None
        assert forbidden_message is not None
        for scope in required_scopes:
            assert scope in caption
            assert scope in forbidden_message

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Zoho CRM token refresh failed: invalid_client",
            "400 Client Error: Bad Request for url: https://accounts.zoho.eu/oauth/v2/token",
            # Blank reason phrase variant (e.g. an HTTP/2 response, which has none).
            "400 Client Error:  for url: https://accounts.zoho.eu/oauth/v2/token",
            "401 Client Error: Unauthorized for url: https://www.zohoapis.com/crm/v8/Leads",
            "403 Client Error: Forbidden for url: https://www.zohoapis.com/crm/v8/Deals",
        ],
    )
    def test_auth_failures_are_non_retryable(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "500 Server Error for url: https://www.zohoapis.com/crm/v8/Leads",
            "429 Client Error: Too Many Requests for url: https://www.zohoapis.com/crm/v8/Leads",
        ],
    )
    def test_transient_failures_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

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

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("Contacts"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZohoCRMResumeConfig
        assert manager._namespace == "Contacts"

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_source_for_pipeline_plumbs_the_incremental_cursor(self, mock_source: mock.MagicMock) -> None:
        manager = mock.MagicMock()
        inputs = _inputs(
            "Deals",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01T00:00:00+00:00",
            incremental_field="Modified_Time",
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["endpoint"] == "Deals"
        assert kwargs["api_version"] == "v8"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01T00:00:00+00:00"
        assert kwargs["incremental_field"] == "Modified_Time"

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_full_refresh_never_forwards_a_stale_watermark(self, mock_source: mock.MagicMock) -> None:
        inputs = _inputs(
            "Leads", should_use_incremental_field=False, db_incremental_field_last_value="2024-06-01T00:00:00+00:00"
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_source_for_pipeline_honors_a_stored_version_pin(self, mock_source: mock.MagicMock) -> None:
        self.source.source_for_pipeline(self.config, mock.MagicMock(), _inputs("Leads", api_version="v7"))

        assert mock_source.call_args.kwargs["api_version"] == "v7"
