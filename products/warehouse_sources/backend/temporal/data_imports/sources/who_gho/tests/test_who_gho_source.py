import datetime

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whogho import WhoGhoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.settings import ENDPOINTS, PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.source import WhoGhoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.who_gho.who_gho import MAX_INDICATOR_CODES


class TestWhoGhoSource:
    def setup_method(self) -> None:
        self.source = WhoGhoSource()
        self.config = WhoGhoSourceConfig(indicator_codes="WHOSIS_000001\nWHOSIS_000002")

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_endpoint_has_a_primary_key_and_canonical_descriptions(self, endpoint: str) -> None:
        assert PRIMARY_KEYS[endpoint]
        assert CANONICAL_DESCRIPTIONS[endpoint]["columns"]

    def test_indicator_data_primary_key_includes_the_indicator_code(self) -> None:
        # One table holds observations for every configured indicator, and each indicator has its
        # own Id sequence (a separate OData entity type per code), so the code has to be part of
        # the key or two indicators could overwrite each other's rows.
        assert PRIMARY_KEYS["indicator_data"] == ["IndicatorCode", "Id"]

    def test_dimension_values_primary_key_is_just_code(self) -> None:
        # Unlike indicator_data, every dimension shares one DIMENSION_VALUE entity type, and the
        # API declares Code as that entity's only key -- it is genuinely unique table-wide.
        assert PRIMARY_KEYS["dimension_values"] == ["Code"]

    def test_non_retryable_error_matches_an_out_of_bounds_code_list(self) -> None:
        config = WhoGhoSourceConfig(
            indicator_codes="\n".join(f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1))
        )

        result = SourceDriver(self.source, config).run("indicator_data", [])

        assert result.raised is not None
        assert error_message_matches(str(result.raised), self.source.get_non_retryable_errors().keys())

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_for_pipeline_plumbs_the_endpoint_through(self, endpoint: str) -> None:
        result = SourceDriver(self.source, self.config).run(endpoint, always(ScriptedResponse(json={"value": []})))

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == PRIMARY_KEYS[endpoint]
        assert result.requests
        if endpoint == "indicator_data":
            assert result.paths == ["/api/WHOSIS_000001", "/api/WHOSIS_000002"]

    def test_source_for_pipeline_formats_the_incremental_watermark_as_a_plain_date(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "indicator_data",
            always(ScriptedResponse(json={"value": []})),
            incremental_field="Date",
            db_incremental_field_last_value=datetime.datetime(2024, 8, 2, 9, 43, 39),
        )

        assert set(result.params("$filter")) == {"date(Date) gt 2024-08-02"}
