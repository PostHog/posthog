from typing import Any, cast

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KoyebSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb import source as koyeb_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.koyeb import KoyebResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.source import KoyebSource
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


class TestKoyebSource:
    def setup_method(self) -> None:
        self.source = KoyebSource()
        self.config = KoyebSourceConfig(api_token="token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.KOYEB

    def test_source_config_metadata(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Koyeb"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Slug must agree with the posthog.com doc filename.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/koyeb"
        # get_schemas is a static catalog, so the public docs can list tables credential-free.
        assert self.source.lists_tables_without_credentials is True

    def test_source_config_fields(self) -> None:
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_token"}
        assert fields["api_token"].required is True
        assert fields["api_token"].secret is True

    def test_get_schemas_incremental_only_for_instances(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == set(ENDPOINTS)

        instances = schemas["instances"]
        assert instances.supports_incremental is True
        assert instances.supports_append is True
        assert [f["field"] for f in instances.incremental_fields] == ["created_at"]
        assert instances.incremental_fields[0]["field_type"] == IncrementalFieldType.DateTime

        for name, schema in schemas.items():
            if name == "instances":
                continue
            assert schema.supports_incremental is False, name
            assert schema.incremental_fields == [], name

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["apps"])
        assert [s.name for s in schemas] == ["apps"]

    @parameterized.expand([("valid", (True, None)), ("invalid", (False, "Invalid or unauthorized Koyeb API token"))])
    def test_validate_credentials_delegates(self, _name: str, result: tuple) -> None:
        with mock.patch.object(koyeb_source_module, "validate_koyeb_credentials", lambda token: result):
            assert self.source.validate_credentials(self.config, team_id=1) == result

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://app.koyeb.com/v1/apps?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://app.koyeb.com/v1/instances?limit=100"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://app.koyeb.com/v1/apps"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://app.koyeb.com/v1/apps"),
            ("read_timeout", "HTTPSConnectionPool(host='app.koyeb.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_resumable_source_manager_binds_data_class(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs("apps"))
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KoyebResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_koyeb_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        manager = MagicMock()
        inputs = _source_inputs(
            "instances",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-01T00:00:00Z",
            incremental_field="created_at",
        )

        with mock.patch.object(koyeb_source_module, "koyeb_source", fake_koyeb_source):
            self.source.source_for_pipeline(self.config, manager, inputs)

        assert captured["api_token"] == "token"
        assert captured["endpoint"] == "instances"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2024-05-01T00:00:00Z"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_koyeb_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock()

        inputs = _source_inputs("apps", should_use_incremental_field=False, db_incremental_field_last_value="stale")
        with mock.patch.object(koyeb_source_module, "koyeb_source", fake_koyeb_source):
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
