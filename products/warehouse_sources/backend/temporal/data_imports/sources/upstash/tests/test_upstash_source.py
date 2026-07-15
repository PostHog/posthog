from typing import Any, cast

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UpstashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash import source as upstash_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.source import UpstashSource
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


class TestUpstashSource:
    def setup_method(self) -> None:
        self.source = UpstashSource()
        self.config = UpstashSourceConfig(email="me@example.com", api_key="key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.UPSTASH

    def test_source_config_metadata(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Upstash"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/upstash"

    def test_source_config_fields(self) -> None:
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in self.source.get_source_config.fields}
        assert set(fields) == {"email", "api_key"}
        assert fields["email"].required is True
        # The management API key is a credential: it must be a secret password field so it is never
        # echoed back or logged in the clear.
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static catalog with no I/O, so the public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_are_all_full_refresh(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}
        assert set(schemas) == {"redis_databases", "redis_stats", "teams", "vector_indexes", "audit_logs"}
        # No Upstash management endpoint exposes a server-side time filter, so none is incremental.
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["teams"])
        assert [s.name for s in schemas] == ["teams"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # Public-docs table catalog must be derivable with no network/credentials.
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == {"redis_databases", "redis_stats", "teams", "vector_indexes", "audit_logs"}
        assert tables["redis_databases"]["sync_methods"] == ["Full refresh"]
        assert tables["redis_databases"]["primary_keys"] == []  # unknown until first sync

    @parameterized.expand(
        [("valid", (True, None)), ("invalid", (False, "Invalid Upstash email or management API key"))]
    )
    def test_validate_credentials_delegates(self, _name: str, result: tuple) -> None:
        with mock.patch.object(upstash_source_module, "validate_upstash_credentials", lambda email, api_key: result):
            assert self.source.validate_credentials(self.config, team_id=1) == result

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.upstash.com/v2/teams"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.upstash.com/auditlogs"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.upstash.com/v2/teams"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.upstash.com/v2/teams"),
            ("read_timeout", "HTTPSConnectionPool(host='api.upstash.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_upstash_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        inputs = _source_inputs("redis_databases")
        with mock.patch.object(upstash_source_module, "upstash_source", fake_upstash_source):
            self.source.source_for_pipeline(self.config, inputs)

        assert captured["email"] == "me@example.com"
        assert captured["api_key"] == "key"
        assert captured["endpoint"] == "redis_databases"
