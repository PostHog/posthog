from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.travisci import (
    TravisCISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source import TravisCISource


def _config() -> TravisCISourceConfig:
    return TravisCISourceConfig(api_token="travis-token")


class TestTravisCISource:
    def setup_method(self) -> None:
        self.source = TravisCISource()
        self.team_id = 123

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "builds"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 278462667
        manager = MagicMock()

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source.travis_ci_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert captured["api_token"] == "travis-token"
        assert captured["endpoint"] == "builds"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == 278462667
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "repositories"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 278462667

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.travis_ci.source.travis_ci_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_config(), MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
