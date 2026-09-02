from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lovable import (
    LovableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.lovable import LovableResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lovable.source import LovableSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.lovable.source"


class TestLovableSource:
    def setup_method(self) -> None:
        self.source = LovableSource()
        self.config = LovableSourceConfig(api_key="lov_key")

    def test_source_config_is_released_with_an_api_key_field(self) -> None:
        config = self.source.get_source_config

        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.iconPath == "/static/services/lovable.png"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.fields is not None
        assert [field.name for field in config.fields] == ["api_key"]
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1)

        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        # No v1 list endpoint takes a timestamp filter, so nothing here can sync incrementally.
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://api.lovable.dev/v1/workspaces"),
            ("402", "402 Client Error: Payment Required for url: https://api.lovable.dev/v1/workspaces/ws-1/members"),
            ("403", "403 Client Error: Forbidden for url: https://api.lovable.dev/v1/projects/p-1/pii-labels"),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.lovable.dev/v1/workspaces"),
            ("server_error", "HTTP 503 for https://api.lovable.dev/v1/workspaces"),
            ("timeout", "Request timed out (ConnectTimeout) for https://api.lovable.dev/v1/workspaces"),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient_failures(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_resumable_manager_is_bound_to_the_resume_config(self) -> None:
        inputs = mock.MagicMock()
        inputs.team_id = 1
        inputs.job_id = "job-1"

        manager = self.source.get_resumable_source_manager(inputs)

        assert manager._data_class is LovableResumeConfig

    @mock.patch(f"{SOURCE_MODULE}.lovable_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_lovable_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Projects"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_lovable_source.call_args.kwargs
        assert kwargs == {
            "api_key": "lov_key",
            "api_version": "v1",
            "endpoint": "Projects",
            "resumable_source_manager": manager,
        }

    @mock.patch(f"{SOURCE_MODULE}.validate_lovable_credentials", return_value=(True, None))
    def test_validate_credentials_resolves_the_api_version(self, mock_validate: mock.MagicMock) -> None:
        assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
        assert mock_validate.call_args.args == ("lov_key", "v1")

    @mock.patch(f"{SOURCE_MODULE}.check_endpoint_permissions", return_value={"Projects": None})
    def test_endpoint_permissions_delegate_to_the_probe(self, mock_check: mock.MagicMock) -> None:
        assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["Projects"]) == {
            "Projects": None
        }
        assert mock_check.call_args.args == ("lov_key", "v1", ["Projects"])
