from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.source import BeamerSource


class TestBeamerSourceConfig:
    def setup_method(self) -> None:
        self.source = BeamerSource()

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — required for the public-docs table list to render.
        assert self.source.lists_tables_without_credentials is True


class TestGetSchemas:
    def setup_method(self) -> None:
        self.schemas = {s.name: s for s in BeamerSource().get_schemas(MagicMock(), team_id=1)}

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
