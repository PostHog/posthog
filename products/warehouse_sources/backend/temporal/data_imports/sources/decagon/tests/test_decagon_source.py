from typing import Any

from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import DecagonResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source import DecagonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DecagonSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(**overrides: Any) -> mock.MagicMock:
    inputs = mock.MagicMock()
    inputs.schema_name = overrides.get("schema_name", "conversations")
    return inputs


class TestDecagonSource:
    def setup_method(self) -> None:
        self.source = DecagonSource()
        self.team_id = 123
        self.config = DecagonSourceConfig(api_key="decagon-test-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DECAGON

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Decagon"
        assert config.label == "Decagon"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True

    def test_get_schemas_is_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        conversations = next(s for s in schemas if s.name == "conversations")
        # /conversation/export has no server-side timestamp filter, so incremental
        # sync must never be advertised for it.
        assert conversations.supports_incremental is False
        assert conversations.supports_append is False
        assert conversations.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["conversations"])] == [
            "conversations"
        ]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error: Unauthorized" in errors
        assert "403 Client Error: Forbidden" in errors

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.validate_decagon_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        mock_validate.return_value = False
        is_valid, message = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is False
        assert message is not None

        mock_validate.assert_called_with(self.config.api_key)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DecagonResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.decagon.source.decagon_source")
    def test_source_for_pipeline_passes_arguments(self, mock_decagon_source: mock.MagicMock) -> None:
        inputs = _make_inputs(schema_name="conversations")
        manager = mock.MagicMock(spec=ResumableSourceManager)

        self.source.source_for_pipeline(self.config, manager, inputs)

        _, kwargs = mock_decagon_source.call_args
        assert kwargs["api_key"] == self.config.api_key
        assert kwargs["endpoint"] == "conversations"
        assert kwargs["resumable_source_manager"] is manager
