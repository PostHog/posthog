from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukcompanieshouse import (
    UkCompaniesHouseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.settings import (
    COMPANIES,
    ENDPOINT_SPECS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uk_companies_house.source import (
    NO_COMPANY_NUMBERS_ERROR,
    UkCompaniesHouseSource,
)


class TestUkCompaniesHouseSource:
    def setup_method(self) -> None:
        self.source = UkCompaniesHouseSource()
        self.config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers="6400\nSC123456")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so it is safe for public docs.
        assert self.source.lists_tables_without_credentials is True

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_keys_are_unique_table_wide(self, endpoint: str) -> None:
        # Every child table aggregates rows from every configured company, so the company the row
        # was fetched for has to be part of the key.
        spec = ENDPOINT_SPECS[endpoint]
        if spec.parent_field is None:
            assert spec.primary_key == ["company_number"]
        else:
            assert spec.parent_field in spec.primary_key

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("blank", "", NO_COMPANY_NUMBERS_ERROR),
            ("separators_only", " , \n ", NO_COMPANY_NUMBERS_ERROR),
            ("malformed_number", "not-a-number", "not valid Companies House company numbers: NOT-A-NUMBER"),
        ]
    )
    def test_validate_credentials_rejects_bad_company_numbers_without_calling_the_api(
        self, _label: str, company_numbers: str, expected_fragment: str
    ) -> None:
        config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers=company_numbers)

        with scripted_network([]) as network:
            ok, error = self.source.validate_credentials(config, team_id=123)

        assert ok is False
        assert error is not None and expected_fragment in error
        assert network.requests_log == []

    def test_validate_credentials_probes_the_first_normalized_company_number(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            ok, error = self.source.validate_credentials(self.config, team_id=123)

        assert (ok, error) == (True, None)
        assert [request.path for request in network.requests_log] == ["/company/00006400"]
        assert network.requests_log[0].headers["authorization"] == "Basic dGVzdC1rZXk6"

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_response_shape(self, endpoint: str) -> None:
        result = SourceDriver(self.source, self.config).run(
            endpoint, [ScriptedResponse(json={}), ScriptedResponse(json={})]
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ENDPOINT_SPECS[endpoint].primary_key
        # Companies House documents no ordering, so the watermark must not be told rows arrive sorted.
        assert response.sort_mode is None

    def test_source_for_pipeline_rejects_an_unknown_endpoint(self) -> None:
        result = SourceDriver(self.source, self.config).run("NotATable", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Companies House endpoint" in str(result.raised)

    def test_source_for_pipeline_rejects_an_empty_company_list(self) -> None:
        config = UkCompaniesHouseSourceConfig(api_key="test-key", company_numbers="")

        result = SourceDriver(self.source, config).run(COMPANIES, [])

        assert isinstance(result.raised, ValueError)
        assert NO_COMPANY_NUMBERS_ERROR in str(result.raised)
