from typing import Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)


class TestAppLovinSource:
    def setup_method(self) -> None:
        self.source = AppLovinSource()
        self.team_id = 123
        self.config = AppLovinSourceConfig(api_key="report-key")

    def test_lists_tables_without_credentials(self) -> None:
        # `get_schemas` is a static catalog, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppLovin Report Key"),
        ],
    )
    def test_validate_credentials(
        self,
        probe_result: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        responses = (
            [ScriptedResponse(json={"code": 200, "results": []})]
            if probe_result
            else [ScriptedResponse(status=403)] * 2
        )
        with scripted_network(responses) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert [request.param("api_key") for request in network.requests_log] == ["report-key"] * len(responses)


class TestAppLovinCanonicalDescriptions:
    def setup_method(self) -> None:
        self.source = AppLovinSource()

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_each_entry_has_a_description_and_docs_url(self, endpoint: str) -> None:
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
