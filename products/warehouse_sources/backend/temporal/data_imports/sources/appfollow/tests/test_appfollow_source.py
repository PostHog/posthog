import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_V2,
    APPFOLLOW_V3,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfollow import (
    AppfollowSourceConfig,
)


class TestAppfollowSource:
    def setup_method(self):
        self.source = AppfollowSource()
        self.team_id = 123
        self.config = AppfollowSourceConfig(api_key="tok_test")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_new_sources_start_on_v3(self):
        assert self.source.default_version == APPFOLLOW_V3
        assert self.source.supported_versions == (APPFOLLOW_V2, APPFOLLOW_V3)

    @pytest.mark.parametrize("api_version", [APPFOLLOW_V2, APPFOLLOW_V3, None])
    def test_get_schemas_covers_all_endpoints(self, api_version):
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "api_version,name,incremental,field",
        [
            (APPFOLLOW_V2, "app_collections", False, None),
            (APPFOLLOW_V2, "app_lists", False, None),
            (APPFOLLOW_V2, "users", False, None),
            (APPFOLLOW_V2, "reviews", True, "updated"),
            (APPFOLLOW_V2, "ratings_history", True, "date"),
            # Only reviews_stats among the ASO/statistics endpoints takes a from/to range; rankings,
            # keywords and app_versions expose no server-side time filter at all.
            (APPFOLLOW_V2, "reviews_stats", True, "date"),
            (APPFOLLOW_V2, "rankings", False, None),
            (APPFOLLOW_V2, "keywords", False, None),
            (APPFOLLOW_V2, "app_versions", False, None),
            # The v3 reviews feed has no last-modified filter, only a from/to range on the review date.
            (APPFOLLOW_V3, "reviews", True, "date"),
            (APPFOLLOW_V3, "app_collections", False, None),
            (APPFOLLOW_V3, "ratings_history", True, "date"),
            (None, "reviews", True, "date"),
        ],
    )
    def test_incremental_capability_per_endpoint(self, api_version, name, incremental, field):
        # Only reviews (server-side last_modified) and ratings_history (server-side from-date) expose a
        # real server filter; the discovery/dimension tables must stay full refresh.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id, api_version=api_version)}
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
            ("rankings", False),
            ("keywords", False),
            ("app_versions", False),
            ("reviews_stats", False),
        ],
    )
    def test_should_sync_defaults(self, name, default_sync):
        # ratings_history and users cost extra credits / are niche, so they're opt-in by default.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[name].should_sync_default is default_sync

    @pytest.mark.parametrize(
        "api_version,name,primary_keys",
        [
            (APPFOLLOW_V2, "app_collections", ["id"]),
            (APPFOLLOW_V2, "app_lists", ["app_collection_id", "app_id"]),
            (APPFOLLOW_V2, "users", ["id"]),
            # Fan-out children must include the parent id so keys stay unique table-wide.
            (APPFOLLOW_V2, "reviews", ["ext_id", "review_id"]),
            (APPFOLLOW_V2, "ratings_history", ["ext_id", "store", "date"]),
            (APPFOLLOW_V2, "rankings", ["ext_id", "country", "device", "genre_id", "date"]),
            (APPFOLLOW_V2, "keywords", ["ext_id", "country", "device", "date", "keyword"]),
            (APPFOLLOW_V2, "app_versions", ["ext_id", "country", "version"]),
            (APPFOLLOW_V2, "reviews_stats", ["ext_id", "date"]),
            (APPFOLLOW_V3, "app_collections", ["collectionId"]),
            (APPFOLLOW_V3, "app_lists", ["collectionId", "itemId"]),
            (APPFOLLOW_V3, "reviews", ["itemId", "id"]),
            (APPFOLLOW_V3, "ratings_history", ["ext_id", "store", "date"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, api_version, name, primary_keys):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id, api_version=api_version)}
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
        "api_version,probed_url",
        [
            (APPFOLLOW_V2, "https://api.appfollow.io/api/v2/account/apps"),
            (APPFOLLOW_V3, "https://api.appfollow.io/api/v3/workspaces"),
            (None, "https://api.appfollow.io/api/v3/workspaces"),
        ],
    )
    def test_validate_credentials_probes_the_pinned_version(self, api_version, probed_url):
        session = mock.MagicMock()
        session.get.return_value.status_code = 200
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.appfollow.make_tracked_session",
            return_value=session,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, api_version=api_version)
        assert ok is True
        assert session.get.call_args.args[0] == probed_url

    @pytest.mark.parametrize("pinned", [APPFOLLOW_V2, APPFOLLOW_V3])
    def test_source_for_pipeline_dispatches_on_the_pin(self, pinned):
        inputs = mock.MagicMock(api_version=pinned, schema_name="reviews", should_use_incremental_field=False)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.appfollow_source"
        ) as appfollow_source:
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert appfollow_source.call_args.kwargs["api_version"] == pinned

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

    def test_documented_tables_render_for_public_docs(self):
        # lists_tables_without_credentials=True must produce a credential-free catalog for posthog.com;
        # a regression in get_schemas' placeholder path would silently empty the docs' Supported tables.
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert "Incremental" in tables["reviews"]["sync_methods"]
        assert tables["app_collections"]["sync_methods"] == ["Full refresh"]
