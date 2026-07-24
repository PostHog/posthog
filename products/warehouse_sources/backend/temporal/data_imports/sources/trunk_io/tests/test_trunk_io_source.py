from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source import TrunkIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io import TrunkIoResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str, **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestTrunkIoSource:
    def setup_method(self):
        self.source = TrunkIoSource()
        self.team_id = 123
        self.config = TrunkIoSourceConfig(
            api_token="test-token",
            org_url_slug="my-org",
            repo_host="github.com",
            repo_owner="my-org",
            repo_name="my-repo",
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TRUNKIO

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static endpoint catalog with no I/O, so it must be safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_get_source_config_is_released(self):
        config = self.source.get_source_config
        assert getattr(config, "unreleasedSource", None) is not True
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_get_source_config_field_names(self):
        field_names = [f.name for f in self.source.get_source_config.fields]
        assert field_names == ["api_token", "org_url_slug", "repo_host", "repo_owner", "repo_name"]

    def test_api_token_field_is_secret(self):
        field = next(f for f in self.source.get_source_config.fields if f.name == "api_token")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.secret is True

    def test_get_schemas_returns_expected_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == {"UnhealthyTests", "QuarantinedTests", "FailingTests"}

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["QuarantinedTests"])
        assert [s.name for s in schemas] == ["QuarantinedTests"]

    @parameterized.expand(
        [
            ("UnhealthyTests", False),
            ("QuarantinedTests", False),
            ("FailingTests", True),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint: str, supports_incremental: bool):
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental

    def test_validate_credentials_delegates_with_repo(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.validate_trunk_io_credentials"
        ) as mock_validate:
            mock_validate.return_value = (True, None)
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (True, None)
        (api_token, org_url_slug, repo), _ = mock_validate.call_args.args, mock_validate.call_args.kwargs
        assert api_token == "test-token"
        assert org_url_slug == "my-org"
        assert repo.host == "github.com"
        assert repo.owner == "my-org"
        assert repo.name == "my-repo"

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = _make_inputs("UnhealthyTests")
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is TrunkIoResumeConfig

    @parameterized.expand(
        [
            ("UnhealthyTests", "unhealthy_tests"),
            ("QuarantinedTests", "quarantined_tests"),
            ("FailingTests", "failing_tests"),
        ]
    )
    def test_source_for_pipeline_dispatches_to_expected_transport(self, schema_name: str, transport_fn: str):
        inputs = _make_inputs(schema_name)
        manager = MagicMock(spec=ResumableSourceManager)

        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.{transport_fn}"
        ) as mock_transport:
            mock_transport.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_transport.assert_called_once()
        assert response.name == schema_name

    def test_source_for_pipeline_unknown_endpoint_raises(self):
        inputs = _make_inputs("NotARealEndpoint")
        manager = MagicMock(spec=ResumableSourceManager)

        try:
            self.source.source_for_pipeline(self.config, manager, inputs)
            raised = False
        except ValueError:
            raised = True

        assert raised

    @parameterized.expand(
        [
            ("UnhealthyTests", ["id"]),
            ("QuarantinedTests", ["name", "parent", "file", "classname", "variant"]),
            ("FailingTests", ["id"]),
        ]
    )
    def test_source_for_pipeline_primary_keys(self, schema_name: str, expected_keys: list[str]):
        inputs = _make_inputs(schema_name)
        manager = MagicMock(spec=ResumableSourceManager)
        transport_fn = {
            "UnhealthyTests": "unhealthy_tests",
            "QuarantinedTests": "quarantined_tests",
            "FailingTests": "failing_tests",
        }[schema_name]

        with patch(
            f"products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.source.{transport_fn}"
        ) as mock_transport:
            mock_transport.return_value = iter([])
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.primary_keys == expected_keys

    def test_get_non_retryable_errors_covers_auth_failures(self):
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)

    def test_get_canonical_descriptions_covers_all_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == {"UnhealthyTests", "QuarantinedTests", "FailingTests"}
