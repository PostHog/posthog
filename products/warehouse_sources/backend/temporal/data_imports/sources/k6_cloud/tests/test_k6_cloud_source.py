from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import K6CloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud import K6CloudResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source import K6CloudSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"test_runs"}


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "test_runs")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    return inputs


class TestK6CloudSource:
    def setup_method(self) -> None:
        self.source = K6CloudSource()
        self.team_id = 123
        self.config = K6CloudSourceConfig(api_token="tok", stack_id="12345")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.K6CLOUD

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "K6Cloud"
        assert config.label == "Grafana Cloud k6"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/k6-cloud"
        assert len(config.fields) == 2

        api_token_field = config.fields[0]
        assert isinstance(api_token_field, SourceFieldInputConfig)
        assert api_token_field.name == "api_token"
        assert api_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_token_field.secret is True

        stack_id_field = config.fields[1]
        assert isinstance(stack_id_field, SourceFieldInputConfig)
        assert stack_id_field.name == "stack_id"
        assert stack_id_field.secret is False

    def test_stack_id_is_a_connection_host_field(self) -> None:
        # `stack_id` routes the stored token to a specific k6 stack, so changing it must re-require
        # the secret — guards against credential retargeting across stacks.
        assert self.source.connection_host_fields == ["stack_id"]

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created"]
        else:
            assert schema.incremental_fields == []

    def test_load_zones_off_by_default(self) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == "load_zones")
        assert schema.should_sync_default is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["projects"])
        assert [s.name for s in schemas] == ["projects"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs table list must render.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize("expected_key", ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"])
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert any(expected_key in key for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token/stack
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "test_runs", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source.validate_k6_cloud_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_token, self.config.stack_id, schema_name)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is K6CloudResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source.k6_cloud_source")
    def test_source_for_pipeline_passes_arguments(self, mock_k6_cloud_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="test_runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_k6_cloud_source.call_args
        assert kwargs["api_token"] == self.config.api_token
        assert kwargs["stack_id"] == self.config.stack_id
        assert kwargs["endpoint"] == "test_runs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source.k6_cloud_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(
        self, mock_k6_cloud_source: mock.MagicMock
    ) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="ignored")
        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        _, kwargs = mock_k6_cloud_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
