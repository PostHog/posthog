import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.testrail import (
    TestrailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.settings import (
    ENDPOINTS,
    TESTRAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source import TestrailSource

INCREMENTAL_ENDPOINTS = {"cases", "runs", "plans", "results"}


class TestTestrailSource:
    def setup_method(self) -> None:
        self.source = TestrailSource()
        self.team_id = 123
        self.config = TestrailSourceConfig(subdomain="acme", username="qa@acme.com", api_key="testrail-key")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to `<subdomain>.testrail.io`; without this, an editor could
        # retarget the subdomain and exfiltrate the preserved key.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_with_correct_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        assert {name for name, s in schemas.items() if s.supports_incremental} == INCREMENTAL_ENDPOINTS
        assert schemas["cases"].incremental_fields[0]["field"] == "updated_on"
        for name in INCREMENTAL_ENDPOINTS - {"cases"}:
            assert schemas[name].incremental_fields[0]["field"] == "created_on"
        for name in set(ENDPOINTS) - INCREMENTAL_ENDPOINTS:
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["cases", "nope"])
        assert [s.name for s in schemas] == ["cases"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["cases"]["sync_methods"]
        assert tables["suites"]["sync_methods"] == ["Full refresh"]

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://acme.testrail.io/index.php?/api/v2/get_projects&limit=250&offset=0",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://acme.testrail.io/index.php?/api/v2/get_cases/1&suite_id=2",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://acme.testrail.io/index.php?"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://acme.testrail.io/index.php?"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source.testrail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "cases"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["username"] == "qa@acme.com"
        assert kwargs["api_key"] == "testrail-key"
        assert kwargs["endpoint"] == "cases"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.testrail.source.testrail_source")
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh sync.
        inputs = mock.MagicMock()
        inputs.schema_name = "cases"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown TestRail schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        # TestRail record IDs are instance-global; a non-unique key would multi-match on merge.
        assert all(config.primary_keys == ["id"] for config in TESTRAIL_ENDPOINTS.values())
        assert set(TESTRAIL_ENDPOINTS) == set(ENDPOINTS)
