from unittest.mock import Mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.source import SleekplanSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.source"


class TestSleekplanSourceConfig:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    def test_source_config_is_released_and_alpha(self) -> None:
        config = self.source.get_source_config

        # A finished source ships with no `unreleasedSource` flag, which would hide it entirely.
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas iterates a static endpoint catalog with no I/O.
        assert self.source.lists_tables_without_credentials is True


class TestSleekplanSourceSchemas:
    def setup_method(self) -> None:
        self.source = SleekplanSource()

    @parameterized.expand(["Users", "Posts", "Comments", "Votes", "Updates"])
    def test_endpoints_without_a_server_side_filter_are_full_refresh_only(self, name: str) -> None:
        # Sleekplan only documents `date_start`/`date_end` on the survey endpoints; advertising
        # incremental anywhere else would page the whole collection and call it a delta.
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[name])

        assert [schema.supports_incremental for schema in schemas] == [False]
        assert [schema.supports_append for schema in schemas] == [False]
        assert schemas[0].incremental_fields == []

    @parameterized.expand(["Satisfaction", "Promoter"])
    def test_survey_endpoints_are_incremental_merge_only(self, name: str) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1, names=[name])

        assert schemas[0].supports_incremental is True
        # Each run re-reads a trailing window, so appending would duplicate rows.
        assert schemas[0].supports_append is False
        assert [field["field"] for field in schemas[0].incremental_fields] == ["updated"]

    def test_every_table_has_canonical_descriptions(self) -> None:
        schemas = self.source.get_schemas(config=Mock(), team_id=1)

        assert {schema.name for schema in schemas} == set(self.source.get_canonical_descriptions())
        assert self.source.get_canonical_descriptions() is CANONICAL_DESCRIPTIONS
