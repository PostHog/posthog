import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nagerdate import (
    NagerDateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.settings import ENDPOINTS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.nager_date.source import NagerDateSource


class TestNagerDateSource:
    def setup_method(self) -> None:
        self.source = NagerDateSource()
        self.config = NagerDateSourceConfig(country_codes="US\nGB")

    @parameterized.expand([("PublicHolidays",), ("NextPublicHolidays",)])
    def test_holiday_tables_key_on_the_synthetic_id(self, endpoint: str) -> None:
        # (countryCode, date, name) alone isn't unique: the same holiday can be split across
        # subdivisions with different classifications, so these tables key on the synthetic id
        # this source adds rather than the raw API fields.
        assert PRIMARY_KEYS[endpoint] == ["id"]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    @time_machine.travel("2026-06-15", tick=False)
    def test_source_for_pipeline_plumbs_the_endpoint_through(self, endpoint: str) -> None:
        result = SourceDriver(self.source, self.config).run(endpoint, always(ScriptedResponse(status=204)))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == PRIMARY_KEYS[endpoint]
        if endpoint == "Countries":
            assert result.paths == ["/api/v4/Countries/Available"]
        elif endpoint == "CountryInfo":
            assert result.paths == ["/api/v4/Countries/US", "/api/v4/Countries/GB"]
        elif endpoint == "NextPublicHolidays":
            assert result.paths == ["/api/v4/Holidays/US/Next", "/api/v4/Holidays/GB/Next"]
        else:
            assert result.paths == [
                f"/api/v4/Holidays/{country}/{year}" for country in ("US", "GB") for year in range(2025, 2032)
            ]
