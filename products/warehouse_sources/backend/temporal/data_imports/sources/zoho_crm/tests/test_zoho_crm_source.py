from collections.abc import Iterator
from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zohocrm import (
    ZohoCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.settings import (
    ENDPOINTS,
    ZOHO_CRM_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.source import ZohoCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zoho_crm.zoho_crm import (
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZOHO_REGIONS,
    ZohoCRMResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

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
        "enabled_columns": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestZohoCRMSource:
    def setup_method(self) -> None:
        self.source = ZohoCRMSource()
        self.team_id = 123
        self.config = ZohoCRMSourceConfig(region="eu", client_id="cid", client_secret="secret", refresh_token="refresh")

    @pytest.fixture(autouse=True)
    def discovered_columns(self) -> Iterator[mock.MagicMock]:
        """Column discovery reaches Zoho's fields metadata API; tests that care stub real fields."""
        with mock.patch(f"{_SOURCE_MODULE}.discover_columns", return_value={}) as discover:
            yield discover

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ZOHOCRM

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "ZohoCRM"
        assert config.label == "Zoho CRM"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/zoho_crm.png"
        assert [field.name for field in config.fields] == ["region", "client_id", "client_secret", "refresh_token"]

    def test_region_options_cover_every_supported_data_center(self) -> None:
        region_field = next(field for field in self.source.get_source_config.fields if field.name == "region")

        assert isinstance(region_field, SourceFieldSelectConfig)
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == set(ZOHO_REGIONS)

    @pytest.mark.parametrize("field_name", ["client_secret", "refresh_token"])
    def test_credentials_are_required_secret_passwords(self, field_name: str) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )

        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_api_version_is_pinned_to_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v8",)
        assert self.source.default_version == "v8"
        assert self.source.api_docs_url.startswith("https://")

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

    def test_get_schemas_lists_every_module(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", INCREMENTAL_ENDPOINTS)
    def test_record_modules_advertise_the_modified_time_cursor(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [field["field"] for field in schema.incremental_fields] == ["Modified_Time"]

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_endpoints_without_a_server_side_filter_are_full_refresh(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    def test_edition_dependent_modules_are_not_ticked_by_default(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["Leads"].should_sync_default is True
        assert schemas["Cases"].should_sync_default is False
        assert schemas["Invoices"].should_sync_default is False

    def test_get_schemas_filters_by_name(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["Deals"])] == ["Deals"]

    def test_get_schemas_with_an_unknown_name_returns_nothing(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_table_catalog_is_publishable_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_column_catalog_is_available_before_the_first_sync(self, discovered_columns: mock.MagicMock) -> None:
        # Without discovery the column picker only fills in after a successful sync, which leaves
        # no way out of a sync that a bad column breaks.
        discovered_columns.return_value = {"Leads": [("id", "bigint", False), ("Last_Name", "text", True)]}

        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["Leads"].columns == [("id", "bigint", False), ("Last_Name", "text", True)]
        assert schemas["Deals"].columns == []

    def test_every_schema_declares_the_record_id_as_its_key(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert all(schema.detected_primary_keys == ["id"] for schema in schemas)

    def test_the_credential_free_catalog_makes_no_metadata_request(self, discovered_columns: mock.MagicMock) -> None:
        self.source.get_schemas(
            ZohoCRMSourceConfig(region="us", client_id="", client_secret="", refresh_token=""), self.team_id
        )

        discovered_columns.assert_not_called()

    def test_only_the_requested_endpoints_are_probed(self, discovered_columns: mock.MagicMock) -> None:
        self.source.get_schemas(self.config, self.team_id, names=["Deals"])

        assert [config.name for config in discovered_columns.call_args.kwargs["endpoints"]] == ["Deals"]

    @mock.patch(f"{_SOURCE_MODULE}.reconcile_source_schema_metadata", return_value=[])
    def test_a_refresh_never_blanks_a_catalog_it_could_not_rediscover(self, reconcile: mock.MagicMock) -> None:
        with_columns = SourceSchema(
            name="Leads", supports_incremental=True, supports_append=True, columns=[("id", "bigint", False)]
        )
        without_columns = SourceSchema(name="Invoices", supports_incremental=True, supports_append=True)

        self.source.reconcile_schema_metadata(mock.MagicMock(), [with_columns, without_columns], self.team_id)

        assert reconcile.call_args.args[1] == [with_columns]
        # Zoho stores selections in raw vendor names but older ones are dlt-normalized; the prune has
        # to fold both sides or it silently empties a pre-discovery selection.
        assert reconcile.call_args.kwargs["normalize_enabled_columns"] is True

    def test_canonical_descriptions_cover_the_published_tables(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        assert all("id" in (entry.get("columns") or {}) for entry in descriptions.values())

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

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_source_for_pipeline_pushes_the_column_selection_down(self, mock_source: mock.MagicMock) -> None:
        inputs = _inputs("Leads", enabled_columns=["Last_Name"])

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["enabled_columns"] == ["Last_Name"]
