from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.settings import (
    AZURE_COST_MANAGEMENT_ENDPOINTS,
    COST_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.source import (
    AzureCostManagementSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azurecostmanagement import (
    AzureCostManagementSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.source"

COST_ENDPOINTS = ("cost_by_service", "cost_by_resource_group", "cost_by_resource", "amortized_cost_by_service")


def _source_inputs(schema_name: str = "cost_by_service", **overrides: Any) -> SourceInputs:
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
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestAzureCostManagementSource:
    def setup_method(self) -> None:
        self.source = AzureCostManagementSource()
        self.config = AzureCostManagementSourceConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            scope="subscriptions/abc",
            start_date=None,
        )

    def test_source_is_released(self) -> None:
        # A truthy `unreleasedSource` hides the connector from users entirely.
        assert not self.source.get_source_config.unreleasedSource

    def test_connection_host_fields_force_secret_reentry_on_retarget(self) -> None:
        # `tenant_id` chooses the Azure AD directory the client secret is exchanged against and
        # `scope` chooses the ARM path the minted token is spent on, so changing either on an
        # existing source must require the secret to be re-entered rather than reusing the stored
        # one against a directory or billing scope it was never connected to.
        assert self.source.connection_host_fields == ["tenant_id", "scope"]

    def test_api_version_metadata(self) -> None:
        assert self.source.supported_versions == ("2025-03-01", "2026-06-01")
        # New sources start on the newest stable version; existing pins are unaffected.
        assert self.source.default_version == "2026-06-01"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` walks a static endpoint catalog with no I/O, so public docs can render it.
        assert self.source.lists_tables_without_credentials is True
        assert {table["name"] for table in self.source.get_documented_tables()} == set(ENDPOINTS)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_name(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["cost_by_service", "dimensions"])

        assert [schema.name for schema in schemas] == ["cost_by_service", "dimensions"]

    @pytest.mark.parametrize("endpoint", COST_ENDPOINTS)
    def test_cost_endpoints_sync_incrementally_on_the_usage_date(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["usage_date"]
        # Azure restates recent days, so each run re-reads a trailing window.
        assert schema.default_incremental_lookback_seconds == COST_LOOKBACK_SECONDS

    @pytest.mark.parametrize("endpoint", ["forecast", "dimensions"])
    def test_non_windowed_endpoints_are_full_refresh(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_no_endpoint_supports_append(self, endpoint: str) -> None:
        # Appending a restated day would materialize a second row for it instead of updating it.
        schema = next(s for s in self.source.get_schemas(self.config, team_id=1) if s.name == endpoint)

        assert schema.supports_append is False

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com — invalid_client",
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com",
            "401 Client Error: Unauthorized for url: https://management.azure.com",
            "403 Client Error: Forbidden for url: https://management.azure.com — no access",
        ],
    )
    def test_non_retryable_errors_match_credential_and_permission_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Azure Cost Management error (retryable): status=429, url=https://management.azure.com/q",
            "500 Server Error for url: https://management.azure.com/q",
        ],
    )
    def test_non_retryable_errors_ignore_transient_failures(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_throttle_exhaustion_is_reported_as_retryable(self) -> None:
        error = "Azure Cost Management error (retryable): status=429, url=https://management.azure.com/q"

        assert any(key in error for key in self.source.get_retryable_errors())

    def test_source_for_pipeline_passes_config_and_schema_through(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs("cost_by_resource")

        with mock.patch(f"{SOURCE_MODULE}.azure_cost_management_source") as build_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = build_source.call_args.kwargs
        assert kwargs["endpoint"] == "cost_by_resource"
        assert kwargs["scope"] == "subscriptions/abc"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["api_version"] == "2026-06-01"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_withholds_the_watermark_on_a_full_refresh(self) -> None:
        inputs = _source_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2024-01-01")

        with mock.patch(f"{SOURCE_MODULE}.azure_cost_management_source") as build_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert build_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_forwards_the_watermark_on_an_incremental_run(self) -> None:
        inputs = _source_inputs(should_use_incremental_field=True, db_incremental_field_last_value="2024-01-01")

        with mock.patch(f"{SOURCE_MODULE}.azure_cost_management_source") as build_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert build_source.call_args.kwargs["db_incremental_field_last_value"] == "2024-01-01"

    @pytest.mark.parametrize(
        "pinned,expected",
        [
            # No pin resolves to the current default; each supported version is honored verbatim so
            # an existing 2025-03-01 pin keeps syncing on its own version after the default flip.
            (None, "2026-06-01"),
            ("2025-03-01", "2025-03-01"),
            ("2026-06-01", "2026-06-01"),
        ],
    )
    def test_source_for_pipeline_honors_a_pinned_api_version(self, pinned: Optional[str], expected: str) -> None:
        inputs = _source_inputs(api_version=pinned)

        with mock.patch(f"{SOURCE_MODULE}.azure_cost_management_source") as build_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        assert build_source.call_args.kwargs["api_version"] == expected

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_canonical_descriptions_cover_every_endpoint(self, endpoint: str) -> None:
        entry = self.source.get_canonical_descriptions()[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
        # Every column in the merge key is described, since those are the ones users join on.
        assert set(AZURE_COST_MANAGEMENT_ENDPOINTS[endpoint].primary_keys) <= set(entry["columns"])

    def test_canonical_descriptions_have_no_stale_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
