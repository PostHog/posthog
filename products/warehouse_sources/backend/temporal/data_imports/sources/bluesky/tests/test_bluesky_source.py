import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import (
    PARTITION_FIELDS,
    PRIMARY_KEYS,
    BlueskySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)


class TestBlueskySource:
    def setup_method(self):
        self.source = BlueskySource()
        self.team_id = 123
        self.config = BlueskySourceConfig(actor="jay.bsky.team")

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # None of Bluesky's list endpoints expose a server-side timestamp filter.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=missing.bsky.social",
        ],
    )
    def test_non_retryable_errors_match_missing_actor(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
            "500 Server Error: Internal Server Error for url: https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
            "HTTPSConnectionPool(host='public.api.bsky.app', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source.bluesky_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bluesky_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Posts"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bluesky_source.assert_called_once_with(
            actor="jay.bsky.team",
            endpoint="Posts",
            team_id=self.team_id,
            job_id="job-1",
            resumable_source_manager=manager,
        )

    @pytest.mark.parametrize(
        ("schema_name", "expected_partition_keys"),
        [
            ("Profile", None),
            ("Posts", ["indexedAt"]),
            ("Followers", ["createdAt"]),
            ("Follows", ["createdAt"]),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source.bluesky_source")
    def test_source_for_pipeline_sets_partitioning_per_endpoint(
        self, mock_bluesky_source, schema_name, expected_partition_keys
    ):
        mock_bluesky_source.return_value.name = schema_name
        mock_bluesky_source.return_value.column_hints = None
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name

        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert response.primary_keys == PRIMARY_KEYS[schema_name]
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)

    def test_every_endpoint_has_primary_keys_declared(self):
        assert set(PRIMARY_KEYS) == set(ENDPOINTS)

    def test_partition_fields_only_cover_multi_row_endpoints(self):
        # Profile is a single row per sync; partitioning it isn't meaningful.
        assert "Profile" not in PARTITION_FIELDS
        assert set(PARTITION_FIELDS) == set(ENDPOINTS) - {"Profile"}
