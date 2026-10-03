from datetime import date

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    ADOBE_ANALYTICS_API_VERSION_2_0,
    ADOBE_ANALYTICS_API_VERSION_V1,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.source import AdobeAnalyticsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobeanalytics import (
    AdobeAnalyticsSourceConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.source"


class TestAdobeAnalyticsSource:
    def setup_method(self) -> None:
        self.source = AdobeAnalyticsSource()
        self.team_id = 123
        self.config = AdobeAnalyticsSourceConfig(
            client_id="cid",
            client_secret="sec",
            report_suite_id="rs1",
            global_company_id="gcid",
        )

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://ims-na1.adobelogin.com/ims/token/v3",
            "401 Client Error: Unauthorized for url: https://analytics.adobe.io/api/gcid/reports",
            "403 Client Error: Forbidden for url: https://analytics.adobe.io/api/gcid/segments",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://analytics.adobe.io/api/gcid/reports",
            "500 Server Error for url: https://analytics.adobe.io/api/gcid/reports",
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
        ],
    )
    def test_non_retryable_errors_do_not_swallow_transient_or_unrelated_failures(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_version_metadata_declares_v1_deprecation(self) -> None:
        # The client only ever spoke Adobe's 2.0 wire, so both pins are request-identical; the
        # metadata is what drives the deprecation banner and the source-level repin migration.
        assert self.source.supported_versions == (ADOBE_ANALYTICS_API_VERSION_V1, ADOBE_ANALYTICS_API_VERSION_2_0)
        assert self.source.default_version == ADOBE_ANALYTICS_API_VERSION_2_0

        deprecation = self.source.get_version_deprecation(ADOBE_ANALYTICS_API_VERSION_V1)
        assert deprecation is not None
        # Adobe's announced 1.4 API end-of-life; the migration and the banner both depend on it.
        assert deprecation.sunset_at == date(2026, 8, 12)
        # The current default must never be flagged deprecated.
        assert self.source.get_version_deprecation(ADOBE_ANALYTICS_API_VERSION_2_0) is None

    def test_get_schemas_lists_the_endpoint_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Only the reporting stream has a server-side date filter to sync incrementally on.
        assert {schema.name for schema in schemas if schema.supports_incremental} == {"report"}

    def test_report_schema_advertises_its_date_cursor(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["report"].incremental_fields == INCREMENTAL_FIELDS["report"]
        assert [f["field"] for f in schemas["report"].incremental_fields] == ["date"]
        assert schemas["segments"].incremental_fields == []
        assert schemas["segments"].supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["report"])

        assert [schema.name for schema in schemas] == ["report"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
        report = next(table for table in tables if table["name"] == "report")
        assert report["primary_keys"] == ["rsid", "date", "item_id"]
        assert report["description"] is not None
