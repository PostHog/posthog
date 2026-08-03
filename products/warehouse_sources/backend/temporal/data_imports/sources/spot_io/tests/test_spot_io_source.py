from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotio import SpotIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source import SpotIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io import SpotIoResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSpotIoSource:
    def setup_method(self) -> None:
        self.source = SpotIoSource()
        self.team_id = 123
        self.config = SpotIoSourceConfig(api_token="spot-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SPOTIO

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SpotIo"
        assert config.label == "Spot by Flexera (Spotinst)"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/spot_io.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/spot-io"

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_account_id_field_is_optional_plain_text(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "account_id")
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.secret is False
        assert field.required is False

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_full_refresh_only(self) -> None:
        # No endpoint has a real per-row server-side timestamp filter to track a watermark from
        # (see settings.py), so every table stays full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["elastigroups"])
        assert len(schemas) == 1
        assert schemas[0].name == "elastigroups"

    @parameterized.expand(
        [
            "401 Client Error: Unauthorized for url: https://api.spotinst.io/aws/ec2/group",
            "403 Client Error: Forbidden for url: https://api.spotinst.io/aws/ec2/group",
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.spotinst.io/aws/ec2/group" for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source.validate_spot_io_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        config = SpotIoSourceConfig(api_token="spot-token", account_id="act-1")
        result = self.source.validate_credentials(config, self.team_id, schema_name="elastigroup_costs")

        assert result == (True, None)
        mock_validate.assert_called_once_with("spot-token", "act-1")

    def test_validate_credentials_normalizes_empty_account_id(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source.validate_spot_io_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            config = SpotIoSourceConfig(api_token="spot-token", account_id="")
            self.source.validate_credentials(config, self.team_id)
            mock_validate.assert_called_once_with("spot-token", None)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SpotIoResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source.spot_io_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_spot_io_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "elastigroup_costs"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        manager = mock.MagicMock()
        config = SpotIoSourceConfig(api_token="spot-token", account_id="act-1")

        self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_spot_io_source.call_args.kwargs
        assert kwargs["api_token"] == "spot-token"
        assert kwargs["account_id"] == "act-1"
        assert kwargs["endpoint"] == "elastigroup_costs"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.source.spot_io_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_spot_io_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "elastigroups"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_spot_io_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
