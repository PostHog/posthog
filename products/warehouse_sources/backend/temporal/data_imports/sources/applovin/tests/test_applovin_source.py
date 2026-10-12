from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source"


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
    @mock.patch(f"{_SOURCE_MODULE}.validate_applovin_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("report-key")


class TestAppLovinCanonicalDescriptions:
    def setup_method(self) -> None:
        self.source = AppLovinSource()

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_each_entry_has_a_description_and_docs_url(self, endpoint: str) -> None:
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
