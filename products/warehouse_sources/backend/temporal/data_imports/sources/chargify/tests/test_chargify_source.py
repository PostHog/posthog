from typing import Any

import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify import ChargifyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import (
    CHARGIFY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source import ChargifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChargifySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Customers",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
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


class TestChargifySource:
    def setup_method(self) -> None:
        self.source = ChargifySource()
        self.team_id = 123
        self.config = ChargifySourceConfig(api_key="test-key", subdomain="acme")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CHARGIFY

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to https://{subdomain}.chargify.com, so changing subdomain
        # must force the key to be re-entered — otherwise it could be exfiltrated to another host.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Chargify"
        assert config.label == "Chargify"
        assert config.category == DataWarehouseSourceCategory.PAYMENTS___BILLING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/chargify"
        assert config.iconPath == "/static/services/chargify.png"

        api_key_field, subdomain_field = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

        assert isinstance(subdomain_field, SourceFieldInputConfig)
        assert subdomain_field.name == "subdomain"
        assert subdomain_field.type == SourceFieldInputConfigType.TEXT
        assert subdomain_field.required is True
        assert subdomain_field.secret is False

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    def test_get_schemas_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint has a curl-verified server-side filter yet, so every schema is full refresh.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Subscriptions"])
        assert [s.name for s in schemas] == ["Subscriptions"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Every advertised endpoint should have a curated description so the docs and the AI
        # agent get authoritative metadata instead of paying for LLM enrichment.
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        ("subdomain", "creds_valid", "expected_valid", "expected_message"),
        [
            ("acme", True, True, None),
            ("acme", False, False, "Invalid Chargify credentials"),
            ("has spaces", True, False, "Chargify site subdomain is invalid"),
            ("bad/slash", True, False, "Chargify site subdomain is invalid"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.validate_chargify_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        subdomain: str,
        creds_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = creds_valid
        config = ChargifySourceConfig(api_key="test-key", subdomain=subdomain)

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    def test_validate_credentials_skips_api_call_for_bad_subdomain(self) -> None:
        # An obviously malformed subdomain must fail before any network call is attempted.
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.validate_chargify_credentials"
        ) as mock_validate:
            config = ChargifySourceConfig(api_key="test-key", subdomain="bad domain")
            is_valid, _ = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChargifyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.chargify_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="Subscriptions", team_id=99, job_id="job-xyz")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            api_key="test-key",
            subdomain="acme",
            endpoint="Subscriptions",
            team_id=99,
            job_id="job-xyz",
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert response.primary_keys == CHARGIFY_ENDPOINTS["Subscriptions"].primary_key

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.chargify_source")
    def test_source_for_pipeline_partitions_on_created_at(self, mock_source: mock.MagicMock) -> None:
        # A stable creation timestamp partitions the table; using created_at (never updated_at)
        # keeps partitions from being rewritten on every sync.
        response = self.source.source_for_pipeline(
            self.config, mock.MagicMock(spec=ResumableSourceManager), _make_inputs(schema_name="Invoices")
        )

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["created_at"]
