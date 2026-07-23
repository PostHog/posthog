import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.streamelements import (
    StreamElementsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source import StreamElementsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.streamelements import (
    StreamElementsResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestStreamElementsSource:
    def setup_method(self) -> None:
        self.source = StreamElementsSource()
        self.team_id = 123
        self.config = StreamElementsSourceConfig(api_token="jwt-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.STREAMELEMENTS

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "StreamElements"
        assert config.label == "StreamElements"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/streamelements.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig))
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.streamelements.com/kappa/v2/channels/me",
            "403 Client Error: Forbidden for url: https://api.streamelements.com/kappa/v2/tips/abc",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.streamelements.com/kappa/v2/tips/abc",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only tips and activities expose StreamElements' server-side `after` datetime filter.
        assert incremental == {"tips", "activities"}
        assert all(schema.supports_append is False for schema in schemas)

    def test_incremental_schemas_advertise_created_at(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["tips"].incremental_fields == INCREMENTAL_FIELDS["tips"]
        assert schemas["points_leaderboard"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tips"])
        assert len(schemas) == 1
        assert schemas[0].name == "tips"

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid StreamElements token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.validate_streamelements_credentials"
    )
    def test_validate_credentials(self, mock_validate: mock.MagicMock, mock_return: tuple[bool, str | None]) -> None:
        mock_validate.return_value = mock_return

        assert self.source.validate_credentials(self.config, self.team_id) == mock_return
        mock_validate.assert_called_once_with(self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is StreamElementsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.streamelements_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tips"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1567780450202
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "jwt-token"
        assert kwargs["endpoint"] == "tips"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1567780450202

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.source.streamelements_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "store_items"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1567780450202

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
