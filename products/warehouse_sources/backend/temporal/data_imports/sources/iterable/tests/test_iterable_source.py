import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IterableSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.iterable import IterableResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source import IterableSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestIterableSource:
    def setup_method(self):
        self.source = IterableSource()
        self.team_id = 123
        self.config = IterableSourceConfig(api_key="fake-key", region="us")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ITERABLE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Iterable"
        assert config.label == "Iterable"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/iterable.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["api_key", "region"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_region_field_offers_us_and_eu(self):
        config = self.source.get_source_config
        region_field = next(f for f in config.fields if isinstance(f, SourceFieldSelectConfig))
        assert region_field.name == "region"
        assert region_field.defaultValue == "us"
        assert {option.value for option in region_field.options} == {"us", "eu"}

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.iterable.com/api/campaigns",
            "403 Client Error: Forbidden for url: https://api.eu.iterable.com/api/templates",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "transient_error",
        [
            "500 Server Error for url: https://api.iterable.com/api/campaigns",
            "429 Client Error: Too Many Requests for url: https://api.iterable.com/api/campaigns",
            "Connection aborted: ReadTimeout for url: https://api.iterable.com/api/campaigns",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, transient_error):
        # Transient failures (5xx / 429 / timeouts) must stay retryable, not permanently fail the job.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh(self):
        # No Iterable list endpoint exposes a verified server-side timestamp filter,
        # so everything is full refresh (no incremental / append).
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == INCREMENTAL_FIELDS[schema.name] == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Iterable API key for the selected data center"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source.validate_iterable_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key, self.config.region)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is IterableResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.iterable.source.iterable_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_iterable_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "campaigns"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_iterable_source.assert_called_once()
        kwargs = mock_iterable_source.call_args.kwargs
        assert kwargs["api_key"] == "fake-key"
        assert kwargs["region"] == "us"
        assert kwargs["endpoint"] == "campaigns"
        assert kwargs["resumable_source_manager"] is manager
