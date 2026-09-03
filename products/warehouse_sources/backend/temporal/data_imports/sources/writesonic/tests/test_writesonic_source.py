from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.writesonic import (
    WritesonicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.settings import (
    ENDPOINTS,
    WRITESONIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source import WritesonicSource


class TestWritesonicSource:
    def setup_method(self):
        self.source = WritesonicSource()
        self.team_id = 123
        self.config = WritesonicSourceConfig(api_key="key_test", site_url="https://example.com")

    def test_connection_host_fields_cover_data_targeting_fields(self):
        # Changing which tracked site the stored API key is used against must force re-entry
        # of the key; dropping either field lets an editor retarget the connection silently.
        assert set(self.source.connection_host_fields) == {"site_url", "project_id"}

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("performance_summary", True),
            ("performance_prompts", True),
            ("performance_answers", True),
            ("content_citations", True),
            ("content_keywords", True),
            ("topics", False),
            ("platforms", False),
            ("websites", False),
            ("prompts", False),
        ]
    )
    def test_incremental_capability_per_endpoint(self, name, incremental):
        # Only the daily exports have a genuine server-side date filter (the required `date`
        # param); the config exports must stay full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is incremental
        if incremental:
            assert [f["field"] for f in schemas[name].incremental_fields] == ["date"]
        else:
            assert schemas[name].incremental_fields == []

    def test_primary_keys_are_exposed(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name, endpoint_config in WRITESONIC_ENDPOINTS.items():
            assert schemas[name].detected_primary_keys == endpoint_config.primary_keys

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["performance_summary"])
        assert len(schemas) == 1
        assert schemas[0].name == "performance_summary"

    @parameterized.expand(
        [
            (
                "401 Client Error: Unauthorized for url: https://api.writesonic.com/v2/geo/presence/business/export/config/topics?url=https%3A%2F%2Fexample.com",
            ),
            (
                "403 Client Error: Forbidden for url: https://api.writesonic.com/v2/geo/presence/business/export/performance/summary",
            ),
            (
                "404 Client Error: Not Found for url: https://api.writesonic.com/v2/geo/presence/business/export/config/websites",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_and_config_failures(self, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
            ("500 Server Error for url: https://api.writesonic.com/v2/geo/presence/business/export/config/topics",),
            ("429 Client Error: Too Many Requests for url: https://api.writesonic.com/v2/geo",),
        ]
    )
    def test_non_retryable_errors_ignore_retryable_and_unrelated(self, unrelated_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_documented_tables_render_for_public_docs(self):
        # lists_tables_without_credentials=True must produce a credential-free catalog for posthog.com;
        # a regression in get_schemas' placeholder path would silently empty the docs' Supported tables.
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["performance_summary"]["sync_methods"]
        assert tables["topics"]["sync_methods"] == ["Full refresh"]
