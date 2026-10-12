from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.similarweb import (
    SimilarwebSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    API_VERSION_LEGACY,
    API_VERSION_V5,
    ENDPOINTS,
    MAX_DOMAINS,
    SIMILARWEB_ENDPOINTS,
    V5_ENGAGEMENT_PATH,
    VISITS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source import SimilarwebSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.source"


class TestSimilarwebSource:
    def setup_method(self) -> None:
        self.source = SimilarwebSource()
        self.team_id = 123
        self.config = SimilarwebSourceConfig(api_key="key-123", domains="posthog.com")

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

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_primary_keys_identify_a_row_across_domains(self, name: str) -> None:
        response = SourceDriver(self.source, self.config).run(name, always(ScriptedResponse(json={}))).response
        assert response is not None

        endpoint = SIMILARWEB_ENDPOINTS[name]
        assert response.name == name
        assert response.primary_keys == endpoint.primary_keys
        # Every table pools rows from every configured domain, so a key without the domain
        # would collapse different domains' rows onto each other on merge.
        assert response.primary_keys is not None and "domain" in response.primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == ([endpoint.partition_key] if endpoint.partition_key else None)

    @parameterized.expand(
        [
            ("unpinned_defaults_to_v5", None, API_VERSION_V5),
            ("legacy_pin_preserved", API_VERSION_LEGACY, API_VERSION_LEGACY),
            ("v5_pin_preserved", API_VERSION_V5, API_VERSION_V5),
        ]
    )
    def test_source_for_pipeline_passes_the_resolved_api_version(
        self, _name: str, pin: str | None, expected: str
    ) -> None:
        result = SourceDriver(self.source, self.config).run(
            VISITS, [ScriptedResponse(json={"data": [], "visits": []})], api_version=pin
        )

        # V5 sends the key in a header to the multi-metric path; the legacy pin keeps the key in the query.
        if expected == API_VERSION_V5:
            assert result.paths == [V5_ENGAGEMENT_PATH]
            assert result.params("api_key") == [None]
            assert result.requests[0].headers["api-key"] == "key-123"
        else:
            assert result.paths != [V5_ENGAGEMENT_PATH]
            assert result.params("api_key") == ["key-123"]
