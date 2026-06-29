from typing import Any, cast

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VercelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import source as vercel_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.source import VercelSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import VercelResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestVercelSource:
    def setup_method(self) -> None:
        self.source = VercelSource()
        self.config = VercelSourceConfig(access_token="token", team_id=None)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.VERCEL

    def test_connection_host_fields_includes_team_id(self) -> None:
        # team_id retargets the stored token at a different Vercel team, so editing it must force
        # the token to be re-entered.
        assert self.source.connection_host_fields == ["team_id"]

    def test_source_config_metadata(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Vercel"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Stays hidden until it's been exercised against the live API.
        assert config.unreleasedSource is True

    def test_source_config_fields(self) -> None:
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in self.source.get_source_config.fields}
        assert set(fields) == {"access_token", "team_id"}
        assert fields["access_token"].required is True
        assert fields["access_token"].secret is True
        # Team scoping is optional — a personal token can sync its own resources.
        assert fields["team_id"].required is False
        assert fields["team_id"].secret is False

    def test_get_schemas_incremental_only_for_deployments(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == {"deployments", "projects", "teams", "domains", "aliases"}

        deployments = schemas["deployments"]
        assert deployments.supports_incremental is True
        assert deployments.supports_append is True
        assert [f["field"] for f in deployments.incremental_fields] == ["created"]
        assert deployments.incremental_fields[0]["field_type"] == IncrementalFieldType.Integer

        for full_refresh in ("projects", "teams", "domains", "aliases"):
            assert schemas[full_refresh].supports_incremental is False
            assert schemas[full_refresh].incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["deployments"])
        assert [s.name for s in schemas] == ["deployments"]

    @parameterized.expand(
        [("valid", (True, None)), ("invalid", (False, "Invalid or unauthorized Vercel access token"))]
    )
    def test_validate_credentials_delegates(self, _name: str, result: tuple) -> None:
        with mock.patch.object(vercel_source_module, "validate_vercel_credentials", lambda token: result):
            assert self.source.validate_credentials(self.config, team_id=1) == result

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vercel.com/v6/deployments?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.vercel.com/v9/projects?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.vercel.com/v6/deployments"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.vercel.com/v6/deployments"),
            ("read_timeout", "HTTPSConnectionPool(host='api.vercel.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("deployments"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is VercelResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        config = VercelSourceConfig(access_token="token", team_id="team_42")
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        manager = MagicMock()
        inputs = _source_inputs(
            "deployments",
            should_use_incremental_field=True,
            db_incremental_field_last_value=123,
            incremental_field="created",
        )

        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(config, manager, inputs)

        assert captured["access_token"] == "token"
        assert captured["team_id"] == "team_42"
        assert captured["endpoint"] == "deployments"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == 123
        assert captured["incremental_field"] == "created"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock()

        inputs = _source_inputs("projects", should_use_incremental_field=False, db_incremental_field_last_value=999)
        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
