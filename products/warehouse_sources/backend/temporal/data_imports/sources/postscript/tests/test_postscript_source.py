from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postscript import (
    PostscriptSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.postscript import (
    PostscriptResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source import PostscriptSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPostscriptSource:
    def setup_method(self) -> None:
        self.source = PostscriptSource()
        self.team_id = 123
        self.config = PostscriptSourceConfig(api_key="sk_postscript")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.POSTSCRIPT

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Postscript"
        assert config.label == "Postscript"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/postscript.png"
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

        # /subscribers is the only endpoint with server-side `__gte` filters; /keywords accepts
        # no query params at all, so declaring it incremental would silently full-scan forever.
        assert schemas["subscribers"].supports_incremental is True
        assert [f["field"] for f in schemas["subscribers"].incremental_fields] == ["updated_at", "created_at"]
        assert schemas["keywords"].supports_incremental is False
        assert schemas["keywords"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["keywords"])
        assert [s.name for s in schemas] == ["keywords"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.postscript.io/api/v2/subscribers",
                True,
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.postscript.io/api/v2/keywords", True),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.postscript.io", False),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.postscript.io", False),
        ]
    )
    def test_non_retryable_errors_match_auth_failures_only(self, _name, observed_error, expect_match) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expect_match

    def test_resolve_api_version_defaults_to_v2(self) -> None:
        assert self.source.resolve_api_version(None) == "v2"
        assert self.source.default_version in self.source.supported_versions

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source.validate_postscript_credentials"
    )
    def test_validate_credentials_plumbs_key_and_resolved_version(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("sk_postscript", "v2")

    def test_get_resumable_source_manager_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is PostscriptResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source.postscript_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_postscript_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "subscribers"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_postscript_source.call_args.kwargs
        assert kwargs["api_key"] == "sk_postscript"
        assert kwargs["endpoint"] == "subscribers"
        assert kwargs["api_version"] == "v2"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source.postscript_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_postscript_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "subscribers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_postscript_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
