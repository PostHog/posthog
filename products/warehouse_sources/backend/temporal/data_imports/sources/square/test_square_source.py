from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SquareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.square.settings import ENDPOINTS, SQUARE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.square.source import SquareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.square.square import SquareResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"payments", "refunds"}


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "payments")
    inputs.should_use_incremental_field = overrides.get("should_use_incremental_field", False)
    inputs.db_incremental_field_last_value = overrides.get("db_incremental_field_last_value", None)
    return inputs


class TestSquareSource:
    def setup_method(self) -> None:
        self.source = SquareSource()
        self.team_id = 123
        self.config = SquareSourceConfig(access_token="EAAA-test", environment="production")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SQUARE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Square"
        assert config.label == "Square"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is not True
        assert len(config.fields) == 2

        access_token_field = config.fields[0]
        assert isinstance(access_token_field, SourceFieldInputConfig)
        assert access_token_field.name == "access_token"
        assert access_token_field.type == SourceFieldInputConfigType.PASSWORD
        assert access_token_field.required is True

        environment_field = config.fields[1]
        assert isinstance(environment_field, SourceFieldSelectConfig)
        assert environment_field.name == "environment"
        assert environment_field.defaultValue == "production"
        assert {o.value for o in environment_field.options} == {"production", "sandbox"}

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(SQUARE_ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["payments"])
        assert len(schemas) == 1
        assert schemas[0].name == "payments"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error: Unauthorized", "403 Client Error: Forbidden"],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "payments", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.square.source.validate_square_credentials"
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
        mock_validate.assert_called_once_with(self.config.access_token, self.config.environment, schema_name)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SquareResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.square.source.square_source")
    def test_source_for_pipeline_passes_arguments(self, mock_square_source: mock.MagicMock) -> None:
        inputs = _make_inputs(
            schema_name="refunds",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_square_source.call_args
        assert kwargs["access_token"] == self.config.access_token
        assert kwargs["environment"] == self.config.environment
        assert kwargs["endpoint"] == "refunds"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.square.source.square_source")
    def test_source_for_pipeline_drops_last_value_when_not_incremental(
        self, mock_square_source: mock.MagicMock
    ) -> None:
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="ignored")
        self.source.source_for_pipeline(self.config, mock.MagicMock(spec=ResumableSourceManager), inputs)

        _, kwargs = mock_square_source.call_args
        assert kwargs["db_incremental_field_last_value"] is None
