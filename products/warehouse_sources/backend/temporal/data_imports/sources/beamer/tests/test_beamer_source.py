from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.source import BeamerSource


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
