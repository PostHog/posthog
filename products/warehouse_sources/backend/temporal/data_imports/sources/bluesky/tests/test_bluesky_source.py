import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky import BlueskyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source import (
    PARTITION_FIELDS,
    PRIMARY_KEYS,
    BlueskySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBlueskySource:
    def setup_method(self):
        self.source = BlueskySource()
        self.team_id = 123
        self.config = BlueskySourceConfig(actor="jay.bsky.team")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BLUESKY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Bluesky"
        assert config.label == "Bluesky"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/bluesky.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/bluesky"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["actor"]

    def test_actor_field_is_required_and_not_secret(self):
        config = self.source.get_source_config
        actor_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "actor")
        assert actor_field.type == SourceFieldInputConfigType.TEXT
        assert actor_field.required is True
        assert actor_field.secret is False

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # None of Bluesky's list endpoints expose a server-side timestamp filter.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Posts"])
        assert len(schemas) == 1
        assert schemas[0].name == "Posts"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

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

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source.validate_bluesky_credentials"
    )
    def test_validate_credentials_delegates_to_transport(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error_message) == (True, None)
        mock_validate.assert_called_once_with("jay.bsky.team")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.source.validate_bluesky_credentials"
    )
    def test_validate_credentials_surfaces_failure(self, mock_validate):
        mock_validate.return_value = (False, "That doesn't look like a valid Bluesky handle or DID.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "That doesn't look like a valid Bluesky handle or DID."

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is BlueskyResumeConfig

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
