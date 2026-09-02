from datetime import date
from typing import Optional, cast

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    ADOBE_ANALYTICS_API_VERSION_2_0,
    ADOBE_ANALYTICS_API_VERSION_V1,
    AdobeAnalyticsResumeConfig,
    adobe_analytics_source,
    validate_credentials as validate_adobe_analytics_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.settings import (
    ADOBE_ANALYTICS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobeanalytics import (
    AdobeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@SourceRegistry.register
class AdobeAnalyticsSource(ResumableSource[AdobeAnalyticsSourceConfig, AdobeAnalyticsResumeConfig]):
    api_docs_url = "https://developer.adobe.com/analytics-apis/docs/2.0/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = (ADOBE_ANALYTICS_API_VERSION_V1, ADOBE_ANALYTICS_API_VERSION_2_0)
    default_version = ADOBE_ANALYTICS_API_VERSION_2_0
    # Adobe sunsets the legacy 1.4 API (the "v1" label) on 2026-08-12; the client already talks
    # 2.0, so this only lights up the generic deprecation warning and repins pins to the label
    # that matches the wire.
    deprecated_versions = (VersionDeprecation(version=ADOBE_ANALYTICS_API_VERSION_V1, sunset_at=date(2026, 8, 12)),)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADOBEANALYTICS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://ims-na1.adobelogin.com": "Adobe rejected your credentials. Check the client ID and secret from your Adobe Developer Console OAuth Server-to-Server credential.",
            "401 Client Error: Unauthorized for url: https://ims-na1.adobelogin.com": "Adobe could not authenticate your credentials. Check the client ID and secret from your Adobe Developer Console OAuth Server-to-Server credential.",
            "401 Client Error: Unauthorized for url: https://analytics.adobe.io": "Adobe Analytics rejected the access token. Reconnect the source with a fresh client ID and secret.",
            "403 Client Error: Forbidden for url: https://analytics.adobe.io": "Adobe Analytics denied access. Check that the Analytics API is added to your Developer Console project and that the credential has a product profile with access to this report suite.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ADOBE_ANALYTICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Adobe Analytics",
            caption="""Pull Adobe Analytics report data and metadata into the PostHog Data warehouse.

Create an **OAuth Server-to-Server** credential in the [Adobe Developer Console](https://developer.adobe.com/console), add the Adobe Analytics API to the project, and assign a product profile that can read the report suite you want. Then enter the credential's client ID and secret.

The report table runs one query per day, so pick the dimension and metrics to break it down by. Adobe allows one dimension per report.""",
            iconPath="/static/services/adobe_analytics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/adobe-analytics",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["adobe", "omniture", "sitecatalyst"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="p8e-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="report_suite_id",
                        label="Report suite ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="examplersid",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="global_company_id",
                        label="Global company ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to detect automatically",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="report_dimension",
                        label="Report dimension",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="variables/daterangeday",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="report_metrics",
                        label="Report metrics",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="metrics/visits,metrics/visitors,metrics/pageviews",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD (defaults to 90 days ago)",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AdobeAnalyticsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = ADOBE_ANALYTICS_ENDPOINTS[schema.name].primary_key
        return schemas

    def validate_credentials(
        self,
        config: AdobeAnalyticsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_adobe_analytics_credentials(
            config.client_id, config.client_secret, config.global_company_id, logger
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdobeAnalyticsResumeConfig]:
        # Report day windows and metadata page numbers are incompatible cursors, so each
        # schema keeps its resume state in its own slot.
        return ResumableSourceManager[AdobeAnalyticsResumeConfig](
            inputs, AdobeAnalyticsResumeConfig, namespace=inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: AdobeAnalyticsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AdobeAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return adobe_analytics_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            global_company_id=config.global_company_id,
            report_suite_id=config.report_suite_id,
            report_dimension=config.report_dimension,
            report_metrics=config.report_metrics,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
