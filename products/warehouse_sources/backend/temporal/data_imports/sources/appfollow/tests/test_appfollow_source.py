import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow import AppfollowResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppfollowSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestAppfollowSource:
    def setup_method(self):
        self.source = AppfollowSource()
        self.team_id = 123
        self.config = AppfollowSourceConfig(api_key="tok_test")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.APPFOLLOW

    def test_get_source_config(self):
        config = self.source.get_source_config
        assert config.name.value == "Appfollow"
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is True
        assert config.iconPath == "/static/services/appfollow.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/appfollow"

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "name,incremental,field",
        [
            ("app_collections", False, None),
            ("app_lists", False, None),
            ("users", False, None),
            ("reviews", True, "updated"),
            ("ratings_history", True, "date"),
        ],
    )
    def test_incremental_capability_per_endpoint(self, name, incremental, field):
        # Only reviews (server-side last_modified) and ratings_history (server-side from-date) expose a
        # real server filter; the discovery/dimension tables must stay full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].supports_incremental is incremental
        if incremental:
            assert [f["field"] for f in schemas[name].incremental_fields] == [field]
        else:
            assert schemas[name].incremental_fields == []

    @pytest.mark.parametrize(
        "name,default_sync",
        [
            ("app_collections", True),
            ("app_lists", True),
            ("reviews", True),
            ("users", False),
            ("ratings_history", False),
        ],
    )
    def test_should_sync_defaults(self, name, default_sync):
        # ratings_history and users cost extra credits / are niche, so they're opt-in by default.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].should_sync_default is default_sync

    @pytest.mark.parametrize(
        "name,primary_keys",
        [
            ("app_collections", ["id"]),
            ("app_lists", ["app_collection_id", "app_id"]),
            ("users", ["id"]),
            # Fan-out children must include the parent id so keys stay unique table-wide.
            ("reviews", ["ext_id", "review_id"]),
            ("ratings_history", ["ext_id", "store", "date"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, name, primary_keys):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].detected_primary_keys == primary_keys

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            # A single account-wide token: a 403 still proves the token is genuine.
            (403, True),
            (401, False),
            (402, False),
            (500, False),
            (None, False),
        ],
    )
    def test_validate_credentials(self, status, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.check_credentials",
            return_value=status,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id)
            assert ok is expected_ok

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.appfollow.io/api/v2/account/apps",
            "402 Client Error: Payment Required for url: https://api.appfollow.io/api/v2/reviews?ext_id=1",
            "403 Client Error: Forbidden for url: https://api.appfollow.io/api/v2/meta/ratings/history",
        ],
    )
    def test_non_retryable_errors_match_auth_and_credit_failures(self, observed_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.appfollow.io/api/v2/reviews",
            "429 Client Error: Too Many Requests for url: https://api.appfollow.io/api/v2/reviews",
        ],
    )
    def test_non_retryable_errors_ignore_retryable_and_unrelated(self, unrelated_error):
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AppfollowResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "reviews"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.appfollow_source"
        ) as appfollow_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
            kwargs = appfollow_source.call_args.kwargs
            assert kwargs["api_key"] == "tok_test"
            assert kwargs["endpoint"] == "reviews"
            assert kwargs["resumable_source_manager"] is manager
            assert kwargs["should_use_incremental_field"] is True
            assert kwargs["db_incremental_field_last_value"] == "2024-01-01"

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        manager = mock.MagicMock()
        inputs = mock.MagicMock()
        inputs.schema_name = "app_collections"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.appfollow_source"
        ) as appfollow_source:
            self.source.source_for_pipeline(self.config, manager, inputs)
            assert appfollow_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_keyed_by_endpoint_names(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(APPFOLLOW_ENDPOINTS)

    def test_documented_tables_render_for_public_docs(self):
        # lists_tables_without_credentials=True must produce a credential-free catalog for posthog.com;
        # a regression in get_schemas' placeholder path would silently empty the docs' Supported tables.
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["reviews"]["sync_methods"]
        assert tables["app_collections"]["sync_methods"] == ["Full refresh"]
