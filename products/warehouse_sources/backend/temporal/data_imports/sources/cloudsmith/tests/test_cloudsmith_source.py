import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith import (
    CloudsmithResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import (
    CLOUDSMITH_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source import CloudsmithSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudsmith import (
    CloudsmithSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCloudsmithSource:
    def setup_method(self) -> None:
        self.source = CloudsmithSource()
        self.team_id = 123
        self.config = CloudsmithSourceConfig(api_key="cloudsmith-key", workspace="acme")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CLOUDSMITH

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Cloudsmith"
        assert config.label == "Cloudsmith"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source ships visible: unreleasedSource hides the connector from every user.
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/cloudsmith.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cloudsmith"

    @pytest.mark.parametrize(
        "name,expected_type,expected_secret",
        [
            ("api_key", SourceFieldInputConfigType.PASSWORD, True),
            ("workspace", SourceFieldInputConfigType.TEXT, False),
        ],
    )
    def test_source_fields(self, name, expected_type, expected_secret) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == name)
        assert field.type == expected_type
        assert field.secret is expected_secret
        assert field.required is True

    def test_get_schemas_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_incremental_semantics(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        # Only the packages list has a server-side time filter (`query=uploaded:>=...`);
        # everything else would have to fetch every page anyway, so it stays full refresh.
        for name in ("repositories", "entitlements", "webhooks", "vulnerabilities", "audit_log", "members", "teams"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

        # packages is merge-only: the `uploaded` bound is inclusive, so each run re-reads the
        # boundary packages and append mode would duplicate them.
        assert schemas["packages"].supports_incremental is True
        assert schemas["packages"].supports_append is False
        assert [f["field"] for f in schemas["packages"].incremental_fields] == ["uploaded_at"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["packages"])
        assert [s.name for s in schemas] == ["packages"]

    @pytest.mark.parametrize(
        "endpoint",
        ["packages", "entitlements", "webhooks"],
    )
    def test_fanout_primary_keys_include_parent_repository(self, endpoint) -> None:
        # These tables aggregate rows from every repository in the workspace, and Cloudsmith
        # only documents `slug_perm` as unique within a repository - a key without the parent
        # would seed duplicate rows that every later merge multi-matches.
        assert CLOUDSMITH_ENDPOINTS[endpoint].primary_key == ["repository_slug", "slug_perm"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.cloudsmith.io/v1/repos/acme/",
            "403 Client Error: Forbidden for url: https://api.cloudsmith.io/v1/packages/acme/prod/",
            "402 Client Error: Payment Required for url: https://api.cloudsmith.io/v1/audit-log/acme/",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_non_retryable_errors_ignore_transient_failures(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://api.cloudsmith.io/v1/repos/acme/" for key in non_retryable
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source.validate_cloudsmith_credentials"
    )
    def test_validate_credentials_plumbs_arguments(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="packages")

        assert result == (True, None)
        mock_validate.assert_called_once_with(api_key="cloudsmith-key", workspace="acme", schema_name="packages")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CloudsmithResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source.cloudsmith_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_cloudsmith_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "packages"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "uploaded_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_cloudsmith_source.call_args.kwargs
        assert kwargs["api_key"] == "cloudsmith-key"
        assert kwargs["workspace"] == "acme"
        assert kwargs["endpoint"] == "packages"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "uploaded_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.source.cloudsmith_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_cloudsmith_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "packages"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_cloudsmith_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)
