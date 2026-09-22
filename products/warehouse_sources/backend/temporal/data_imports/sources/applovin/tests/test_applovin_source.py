from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import TRANSIENT_ERROR_PREFIX
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
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

    def test_get_schemas(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Every endpoint filters server-side on `day` via start/end.
            assert schema.supports_incremental is True
            assert schema.incremental_fields == INCREMENTAL_FIELDS[name]
            # Aggregate rows restate for a few days, so append would duplicate them.
            assert schema.supports_append is False
            assert schema.detected_primary_keys == APPLOVIN_ENDPOINTS[name].primary_keys

    @pytest.mark.parametrize(
        "names, expected",
        [
            (["max_ad_revenue"], ["max_ad_revenue"]),
            (["max_cohort_sessions", "publisher_report"], ["publisher_report", "max_cohort_sessions"]),
            (["nope"], []),
        ],
    )
    def test_get_schemas_filtered_by_names(self, names: list[str], expected: list[str]) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=names)

        assert sorted(schema.name for schema in schemas) == sorted(expected)

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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AppLovin request failed: HTTPSConnectionPool(host='r.applovin.com', port=443): timed out",
            f"{TRANSIENT_ERROR_PREFIX}: status=503, endpoint=/maxReport",
            f"{TRANSIENT_ERROR_PREFIX}: status=429, endpoint=/report",
            "500 Server Error for url: https://r.applovin.com/maxReport",
        ],
    )
    def test_transient_errors_stay_retryable(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())


class TestAppLovinCanonicalDescriptions:
    def setup_method(self) -> None:
        self.source = AppLovinSource()

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_documented_columns_are_columns_the_source_requests(self, endpoint: str) -> None:
        # A typo here would ship a description for a column that never lands in the table.
        documented = set(CANONICAL_DESCRIPTIONS[endpoint].get("columns", {}))
        assert documented <= set(APPLOVIN_ENDPOINTS[endpoint].columns)
        assert documented == set(APPLOVIN_ENDPOINTS[endpoint].columns)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_each_entry_has_a_description_and_docs_url(self, endpoint: str) -> None:
        entry = CANONICAL_DESCRIPTIONS[endpoint]

        assert entry["description"]
        assert str(entry["docs_url"]).startswith("https://")
