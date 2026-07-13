from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WritesonicSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.settings import (
    ENDPOINTS,
    WRITESONIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source import WritesonicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.writesonic import (
    WritesonicResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWritesonicSource:
    def setup_method(self):
        self.source = WritesonicSource()
        self.team_id = 123
        self.config = WritesonicSourceConfig(api_key="key_test", site_url="https://example.com")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WRITESONIC

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "Writesonic"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/writesonic.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/writesonic"

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_site_url_required_and_project_id_optional(self):
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert fields["site_url"].required is True
        assert fields["project_id"].required is False

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

    def test_validate_credentials_plumbs_config(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source.validate_writesonic_credentials",
            return_value=(True, None),
        ) as validate:
            ok, message = self.source.validate_credentials(self.config, self.team_id, schema_name="topics")
            assert ok is True
            assert message is None
            kwargs = validate.call_args.kwargs
            assert kwargs["api_key"] == "key_test"
            assert kwargs["site_url"] == "https://example.com"
            assert kwargs["project_id"] is None
            assert kwargs["schema_name"] == "topics"

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

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is WritesonicResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "performance_summary"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source.writesonic_source"
        ) as source_fn:
            self.source.source_for_pipeline(self.config, manager, inputs)
            kwargs = source_fn.call_args.kwargs
            assert kwargs["api_key"] == "key_test"
            assert kwargs["site_url"] == "https://example.com"
            assert kwargs["endpoint"] == "performance_summary"
            assert kwargs["manager"] is manager
            assert kwargs["should_use_incremental_field"] is True
            assert kwargs["db_incremental_field_last_value"] == "2026-07-01"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "topics"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.writesonic.source.writesonic_source"
        ) as source_fn:
            self.source.source_for_pipeline(self.config, manager, inputs)
            assert source_fn.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keyed_by_endpoint_names(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(WRITESONIC_ENDPOINTS)

    def test_documented_tables_render_for_public_docs(self):
        # lists_tables_without_credentials=True must produce a credential-free catalog for posthog.com;
        # a regression in get_schemas' placeholder path would silently empty the docs' Supported tables.
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["performance_summary"]["sync_methods"]
        assert tables["topics"]["sync_methods"] == ["Full refresh"]
