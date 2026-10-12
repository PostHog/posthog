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
