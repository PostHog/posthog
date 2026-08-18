import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kickscale import (
    KickscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.kickscale import KickscaleResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.settings import (
    ENDPOINTS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source import KickscaleSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestKickscaleSource:
    def setup_method(self) -> None:
        self.source = KickscaleSource()
        self.team_id = 123
        self.config = KickscaleSourceConfig(api_key="kickscale-key", client_id="kickscale-client")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KICKSCALE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Kickscale"
        assert config.label == "Kickscale"
        assert config.category == DataWarehouseSourceCategory.SALES
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/kickscale.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_fields_have_correct_secrecy(self) -> None:
        config = self.source.get_source_config
        fields = {f.name: f for f in config.fields}
        assert set(fields) == {"api_key", "client_id"}

        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

        client_id_field = fields["client_id"]
        assert isinstance(client_id_field, SourceFieldInputConfig)
        assert client_id_field.type == SourceFieldInputConfigType.TEXT
        assert client_id_field.secret is False
        assert client_id_field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        for name in ENDPOINTS:
            assert schemas[name].supports_incremental is True, name
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"], name
            assert schemas[name].default_incremental_lookback_seconds == INCREMENTAL_LOOKBACK_SECONDS, name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [s.name for s in schemas] == ["calls"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("403 Client Error: Forbidden for url: https://api.kickscale.com/meetings", True),
            ("401 Client Error: Unauthorized for url: https://api.kickscale.com/meetings", False),
            ("500 Server Error: Internal Server Error for url: https://api.kickscale.com/meetings", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source.validate_kickscale_credentials"
    )
    def test_validate_credentials_plumbs_both_headers(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("kickscale-key", "kickscale-client")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is KickscaleResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source.kickscale_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_kickscale_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "meetings"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "date"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_kickscale_source.call_args.kwargs
        assert kwargs["api_key"] == "kickscale-key"
        assert kwargs["client_id"] == "kickscale-client"
        assert kwargs["endpoint"] == "meetings"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "date"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.source.kickscale_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_kickscale_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "meetings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_kickscale_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
