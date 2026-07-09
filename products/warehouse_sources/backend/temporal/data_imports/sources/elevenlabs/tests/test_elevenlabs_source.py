import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.elevenlabs import (
    ElevenLabsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source import ElevenLabsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ElevenLabsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestElevenLabsSource:
    def setup_method(self):
        self.source = ElevenLabsSource()
        self.team_id = 123
        self.config = ElevenLabsSourceConfig(api_key="key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ELEVENLABS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "ElevenLabs"
        assert config.label == "ElevenLabs"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/elevenlabs.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/elevenlabs"

    def test_source_config_fields(self):
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["api_key"]

        api_key = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True

    def test_lists_tables_without_credentials(self):
        # get_schemas iterates a static endpoint catalog with no I/O, so the public docs catalog renders.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert [t["name"] for t in documented] == list(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, supports_incremental",
        [
            ("history", True),
            ("conversations", True),
            ("agents", False),
            ("voices", False),
            ("models", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint, supports_incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        assert schema.incremental_fields == INCREMENTAL_FIELDS.get(endpoint, [])

    def test_get_schemas_filtered_by_names(self):
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["history"])] == ["history"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.elevenlabs.io/v1/history?page_size=1000",
            "403 Client Error: Forbidden for url: https://api.elevenlabs.io/v1/convai/conversations?page_size=100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.elevenlabs.io/v1/history",
            "429 Client Error: Too Many Requests for url: https://api.elevenlabs.io/v1/history",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_or_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid ElevenLabs API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source.validate_elevenlabs_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ElevenLabsResumeConfig

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.elevenlabs.source.elevenlabs_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_elevenlabs_source, should_use_incremental_field):
        inputs = mock.MagicMock()
        inputs.schema_name = "history"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = 1700000000
        inputs.incremental_field = "date_unix"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_elevenlabs_source.assert_called_once()
        kwargs = mock_elevenlabs_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "history"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        # The stored watermark must never leak into a full-refresh run.
        assert kwargs["db_incremental_field_last_value"] == (1700000000 if should_use_incremental_field else None)

    def test_canonical_descriptions_keyed_by_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
