from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.select_star.source import SelectStarSource


class TestSelectStarSource:
    def setup_method(self):
        self.source = SelectStarSource()
        self.team_id = 42

    def test_source_is_released(self):
        # A finished source must be visible: no unreleasedSource flag, soft ALPHA label.
        config = self.source.get_source_config
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so public docs may render the table list.
        assert self.source.lists_tables_without_credentials is True
