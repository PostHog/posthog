from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.source import BeamerSource


class TestBeamerSourceConfig:
    def setup_method(self) -> None:
        self.source = BeamerSource()

    def test_config_is_released_alpha(self) -> None:
        config = self.source.get_source_config
        # A finished source is visible (no unreleasedSource) and labelled alpha.
        assert config.unreleasedSource is None
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/beamer"

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in BeamerSource().get_schemas(MagicMock(), team_id=1)}

    def test_all_expected_tables_present(self) -> None:
        assert set(self.schemas) == {
            "posts",
            "feature_requests",
            "nps",
            "users",
            "post_comments",
            "post_reactions",
            "feature_request_comments",
            "feature_request_votes",
        }

    @parameterized.expand(["posts", "feature_requests", "nps"])
    def test_top_level_collections_are_incremental(self, name: str) -> None:
        schema = self.schemas[name]
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["date"]

    @parameterized.expand(
        ["users", "post_comments", "post_reactions", "feature_request_comments", "feature_request_votes"]
    )
    def test_full_refresh_only_tables(self, name: str) -> None:
        assert self.schemas[name].supports_incremental is False

    def test_scale_only_and_high_volume_tables_off_by_default(self) -> None:
        assert self.schemas["users"].should_sync_default is False
        assert self.schemas["post_reactions"].should_sync_default is False
        assert self.schemas["posts"].should_sync_default is True

    def test_names_filter(self) -> None:
        filtered = BeamerSource().get_schemas(MagicMock(), team_id=1, names=["posts"])
        assert [s.name for s in filtered] == ["posts"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.getbeamer.com/v0/posts?maxResults=1"),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.getbeamer.com/v0/users?maxResults=100&page=1",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BeamerSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.getbeamer.com/v0/posts"),
            ("read_timeout", "HTTPSConnectionPool(host='api.getbeamer.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = BeamerSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)
