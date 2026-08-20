from typing import Any, cast

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singlestore import (
    SinglestoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore import (
    source as singlestore_source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.source import SinglestoreSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


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


class TestSinglestoreSource:
    def setup_method(self) -> None:
        self.source = SinglestoreSource()
        self.config = SinglestoreSourceConfig(api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SINGLESTORE

    def test_source_config_metadata(self) -> None:
        config = self.source.get_source_config
        assert config.label == "SingleStore, Inc."
        assert config.category == DataWarehouseSourceCategory.DATABASES
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/singlestore"
        # A finished source must never ship hidden behind this flag.
        assert config.unreleasedSource is not True

    def test_source_config_fields(self) -> None:
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in self.source.get_source_config.fields}
        assert set(fields) == {"api_key"}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == {"organization", "regions", "workspace_groups", "workspaces", "billing_usage"}

    @parameterized.expand(
        [
            ("organization",),
            ("regions",),
            ("workspace_groups",),
            ("workspaces",),
        ]
    )
    def test_dimension_schemas_are_full_refresh(self, name: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert schemas[name].supports_incremental is False
        assert schemas[name].incremental_fields == []

    def test_billing_usage_schema_is_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert schemas["billing_usage"].supports_incremental is True
        assert [f["field"] for f in schemas["billing_usage"].incremental_fields] == ["startTime"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["regions"])
        assert [s.name for s in schemas] == ["regions"]

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == {"organization", "regions", "workspace_groups", "workspaces", "billing_usage"}
        assert tables["organization"]["description"]
        assert tables["billing_usage"]["sync_methods"] == ["Incremental", "Full refresh"]

    @parameterized.expand(
        [
            ("valid", (True, None)),
            (
                "invalid",
                (
                    False,
                    "SingleStore rejected the API key. Generate a new organization API key in the Cloud Portal and try again.",
                ),
            ),
        ]
    )
    def test_validate_credentials_delegates(self, _name: str, result: tuple) -> None:
        with mock.patch.object(singlestore_source_module, "validate_singlestore_credentials", lambda api_key: result):
            assert self.source.validate_credentials(self.config, team_id=1) == result

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.singlestore.com/v1/organizations/current",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.singlestore.com/v1/workspaces"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.singlestore.com/v1/workspaces"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.singlestore.com/v1/regions"),
            ("read_timeout", "HTTPSConnectionPool(host='api.singlestore.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_singlestore_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(name="source_response")

        inputs = _source_inputs(
            "billing_usage", should_use_incremental_field=True, db_incremental_field_last_value="2026-01-01"
        )
        with mock.patch.object(singlestore_source_module, "singlestore_source", fake_singlestore_source):
            self.source.source_for_pipeline(self.config, inputs)

        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "billing_usage"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01"
