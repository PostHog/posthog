from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo import (
    CRITEO_NO_ADVERTISERS_ERROR,
    CriteoResumeConfig,
    criteo_source,
    validate_credentials as validate_criteo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    CRITEO_API_VERSION,
    CRITEO_BASE_URL,
    CRITEO_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.criteo import CriteoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CriteoSource(ResumableSource[CriteoSourceConfig, CriteoResumeConfig]):
    supported_versions = (CRITEO_API_VERSION,)
    default_version = CRITEO_API_VERSION
    api_docs_url = "https://developers.criteo.com/marketing-solutions/reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRITEO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Permanent token-exchange failures (invalid_client, unauthorized_client, …) all carry the
            # framework's stable marker; transient 429/5xx token errors don't.
            OAUTH2_PERMANENT_ERROR_MARKER: "Criteo rejected these credentials. Please check your client ID and client secret.",
            f"403 Client Error: Forbidden for url: {CRITEO_BASE_URL}": "Criteo denied access. Please check that your app has the scope this table needs and that an advertiser admin has granted it access.",
            CRITEO_NO_ADVERTISERS_ERROR: None,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CRITEO,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Criteo",
            caption="""Enter your Criteo API credentials to pull your Criteo Marketing Solutions data into the PostHog Data warehouse.

Create an app in the [Criteo Partners Portal](https://partners.criteo.com), generate client credentials for it, then have an advertiser admin grant the app access through its consent URL. No data is readable until that grant is in place. Add the read scopes for the tables you want: `MarketingSolutions_Campaign_Read` for campaigns and ad sets, `MarketingSolutions_Creative_Read` for ads, and `MarketingSolutions_Audience_Read` for audiences.

Campaign statistics are pulled per day. Set the currency you report in, otherwise USD is used.""",
            iconPath="/static/services/criteo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/criteo",
            releaseStatus=ReleaseStatus.ALPHA,
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
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="report_currency",
                        label="Reporting currency",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="USD",
                        secret=False,
                        caption="Three-letter currency code for campaign statistics. Defaults to USD.",
                    ),
                    SourceFieldInputConfig(
                        name="report_timezone",
                        label="Reporting time zone",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="UTC",
                        secret=False,
                        caption="Time zone the statistics days are bucketed in, for example Europe/Paris. Defaults to UTC.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CriteoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=MERGE_ONLY_ENDPOINTS,
        )
        for schema in schemas:
            schema.default_incremental_lookback_seconds = CRITEO_ENDPOINTS[
                schema.name
            ].default_incremental_lookback_seconds
        return schemas

    def validate_credentials(
        self,
        config: CriteoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_criteo_credentials(
            config.client_id, config.client_secret, self.resolve_api_version(api_version)
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CriteoResumeConfig]:
        # Endpoints store incompatible cursors (an offset, a fanned-out advertiser, a report day), so
        # each keeps its resume state in its own slot.
        return ResumableSourceManager[CriteoResumeConfig](inputs, CriteoResumeConfig).with_namespace(inputs.schema_name)

    def source_for_pipeline(
        self,
        config: CriteoSourceConfig,
        resumable_source_manager: ResumableSourceManager[CriteoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return criteo_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            report_currency=config.report_currency,
            report_timezone=config.report_timezone,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
