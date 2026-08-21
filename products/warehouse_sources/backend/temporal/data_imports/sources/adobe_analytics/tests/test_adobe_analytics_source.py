from datetime import date

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    ADOBE_ANALYTICS_API_VERSION_2_0,
    ADOBE_ANALYTICS_API_VERSION_V1,
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
