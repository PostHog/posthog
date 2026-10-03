from unittest.mock import MagicMock, patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source import HerokuSource

SOURCE_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.heroku.source"


class TestHerokuSource:
    def setup_method(self) -> None:
        self.source = HerokuSource()

    def test_get_schemas_returns_full_refresh_only_endpoints(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)

        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Heroku has no server-side timestamp filters; flipping any of these on without one
        # would sync incorrect incremental data.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

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

    def test_non_retryable_error_keys_match_requests_error_strings(self) -> None:
        # `get_non_retryable_errors` keys are matched as substrings of the raised error; if
        # the key format drifts from what requests actually produces, credential failures
        # retry forever instead of disabling the source.
        response = requests.Response()
        response.status_code = 401
        response.reason = "Unauthorized"  # verified live: Heroku sends this phrase over HTTP/1.1
        response.url = "https://api.heroku.com/apps/some-app/releases"
        try:
            response.raise_for_status()
            raise AssertionError("raise_for_status did not raise")
        except requests.HTTPError as e:
            error_string = str(e)

        assert any(key in error_string for key in self.source.get_non_retryable_errors())
