from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.similarweb import (
    SimilarwebSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    API_VERSION_LEGACY,
    API_VERSION_V5,
    ENDPOINTS,
    MAX_DOMAINS,
    SIMILARWEB_ENDPOINTS,
    TRAFFIC_BY_COUNTRY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source import SimilarwebSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source"


class TestSimilarwebSource:
    def setup_method(self) -> None:
        self.source = SimilarwebSource()
        self.team_id = 123
        self.config = SimilarwebSourceConfig(api_key="key-123", domains="posthog.com")

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        by_name = {schema.name: schema for schema in schemas}
        for name, endpoint in SIMILARWEB_ENDPOINTS.items():
            assert by_name[name].description == endpoint.description
            # The geo breakdown aggregates the whole window into rows with no period column,
            # so it must not advertise a cursor the pipeline would try to advance.
            assert by_name[name].supports_incremental is (name != TRAFFIC_BY_COUNTRY)
            if name != TRAFFIC_BY_COUNTRY:
                assert {field["field"] for field in by_name[name].incremental_fields} == {"date"}

    @parameterized.expand(
        [
            ("no_domains", {"domains": " "}, "Add at least one domain"),
            (
                "too_many_domains",
                {"domains": ",".join(f"d{i}.com" for i in range(MAX_DOMAINS + 1))},
                "Too many domains",
            ),
            ("bad_country", {"country": "usa"}, "two-letter code"),
            ("bad_start_month", {"start_date": "01-2024"}, "YYYY-MM format"),
        ]
    )
    def test_validate_credentials_rejects_bad_settings_without_calling_the_api(
        self, _name: str, overrides: dict[str, Any], expected: str
    ) -> None:
        config = SimilarwebSourceConfig(**{"api_key": "key-123", "domains": "posthog.com", **overrides})

        with mock.patch(f"{MODULE}.validate_similarweb_credentials") as probe:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and expected in message
        probe.assert_not_called()

    def test_validate_credentials_probes_the_api_when_settings_are_valid(self) -> None:
        with mock.patch(f"{MODULE}.validate_similarweb_credentials", return_value=(True, None)) as probe:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        probe.assert_called_once_with("key-123")

    def test_declares_v5_as_default_over_legacy(self) -> None:
        assert self.source.supported_versions == (API_VERSION_LEGACY, API_VERSION_V5)
        assert self.source.default_version == API_VERSION_V5
