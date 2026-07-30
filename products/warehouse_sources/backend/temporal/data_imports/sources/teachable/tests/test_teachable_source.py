import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teachable import (
    TeachableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.settings import (
    ENDPOINTS,
    TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source import TeachableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable import TeachableResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTeachableSource:
    def setup_method(self) -> None:
        self.source = TeachableSource()
        self.team_id = 123
        self.config = TeachableSourceConfig(api_key="teachable-key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.TEACHABLE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Teachable"
        assert config.label == "Teachable"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/teachable.png"
        # The source ships visible — a truthy unreleasedSource hides it from every user.
        assert not config.unreleasedSource

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["api_key"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Only /transactions has a server-side time filter (`start`); everything else is
        # full refresh.
        assert schemas["transactions"].supports_incremental is True
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["created_at"]
        assert schemas["transactions"].default_incremental_lookback_seconds == TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS

        for name in ("users", "courses", "course_enrollments", "pricing_plans"):
            assert schemas[name].supports_incremental is False, name
            assert schemas[name].incremental_fields == [], name

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert [s.name for s in schemas] == ["transactions"]

    @pytest.mark.parametrize(
        "observed_error,expect_match",
        [
            ("401 Client Error: Unauthorized for url: https://developers.teachable.com/v1/users", True),
            ("403 Client Error: Forbidden for url: https://developers.teachable.com/v1/courses", True),
            ("500 Server Error: Internal Server Error for url: https://developers.teachable.com/v1/users", False),
        ],
    )
    def test_non_retryable_errors_match_auth_failures_only(self, observed_error: str, expect_match: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source.validate_teachable_credentials"
    )
    def test_validate_credentials_plumbs_api_key(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("teachable-key",)

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is TeachableResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source.teachable_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_teachable_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "created_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_teachable_source.call_args.kwargs
        assert kwargs["api_key"] == "teachable-key"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "created_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teachable.source.teachable_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_teachable_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_teachable_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
