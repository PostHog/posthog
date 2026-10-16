from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source import HerokuSource

SOURCE_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source"


class TestHerokuSource:
    def setup_method(self) -> None:
        self.source = HerokuSource()

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["apps", "releases"])
        assert {s.name for s in schemas} == {"apps", "releases"}

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    def test_validate_credentials_maps_probe_result(self) -> None:
        config = MagicMock()
        config.api_key = "key"

        with patch(f"{SOURCE_PATH}.validate_heroku_credentials", return_value=True) as probe:
            assert self.source.validate_credentials(config, team_id=1) == (True, None)
        probe.assert_called_once_with("key")

        with patch(f"{SOURCE_PATH}.validate_heroku_credentials", return_value=False):
            valid, message = self.source.validate_credentials(config, team_id=1)
        assert not valid
        assert message == "Invalid Heroku API key"
