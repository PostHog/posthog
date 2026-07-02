from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic import EConomicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source import EConomicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EConomicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"customers", "products", "invoices_booked"}


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "customers")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    inputs.incremental_field = overrides.get("incremental_field", None)
    return inputs


class TestECONomicSource:
    def setup_method(self) -> None:
        self.source = EConomicSource()
        self.team_id = 123
        self.config = EConomicSourceConfig(app_secret_token="secret", agreement_grant_token="grant")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.ECONOMIC

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "EConomic"
        assert config.label == "e-conomic"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is not True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/e-conomic"

        assert [f.name for f in config.fields] == ["app_secret_token", "agreement_grant_token"]
        for token_field in config.fields:
            assert isinstance(token_field, SourceFieldInputConfig)
            assert token_field.type == SourceFieldInputConfigType.PASSWORD
            assert token_field.required is True
            assert token_field.secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O), so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        assert schema.incremental_fields == INCREMENTAL_FIELDS[endpoint]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert [s.name for s in schemas] == ["customers"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize("expected_key", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "is_valid, expected_valid, expected_has_message",
        [(True, True, False), (False, False, True)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source.validate_e_conomic_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        is_valid: bool,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = is_valid
        valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.app_secret_token, self.config.agreement_grant_token)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is EConomicResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source.e_conomic_source")
    def test_source_for_pipeline_passes_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="customers",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="lastUpdated",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["app_secret_token"] == self.config.app_secret_token
        assert kwargs["agreement_grant_token"] == self.config.agreement_grant_token
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "lastUpdated"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.source.e_conomic_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="ignored")
        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
