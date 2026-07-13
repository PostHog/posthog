import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MaxioSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.maxio import (
    MaxioResumeConfig,
    maxio_source,
    normalize_subdomain,
    validate_credentials as validate_maxio_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.settings import (
    ENDPOINTS,
    TIMEZONE_SKEW_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MaxioSource(ResumableSource[MaxioSourceConfig, MaxioResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAXIO

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to the host derived from these fields; retargeting
        # either must re-require the key.
        return ["subdomain", "region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Maxio rejected the API key. Generate a new API key for the site and reconnect.",
            "403 Client Error": "The Maxio API key does not have access to this resource.",
            "404 Client Error": "Maxio site not found. Check the subdomain and hosting region.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.maxio.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MaxioSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=len(endpoint.incremental_fields) > 0,
                supports_append=len(endpoint.incremental_fields) > 0,
                incremental_fields=endpoint.incremental_fields,
                # Datetime windows are interpreted in the site's timezone — re-read a
                # trailing day to cover the skew. Integer cursors (`since_id`) are exact.
                default_incremental_lookback_seconds=(
                    TIMEZONE_SKEW_LOOKBACK_SECONDS if endpoint.incremental_date_field else None
                ),
            )
            for name, endpoint in ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MaxioSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        subdomain = normalize_subdomain(config.subdomain)
        if not re.match(r"^[a-zA-Z0-9-]+$", subdomain):
            return False, "Maxio subdomain is incorrect"

        return validate_maxio_credentials(config.api_key, subdomain, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MaxioResumeConfig]:
        return ResumableSourceManager[MaxioResumeConfig](inputs, MaxioResumeConfig)

    def source_for_pipeline(
        self,
        config: MaxioSourceConfig,
        resumable_source_manager: ResumableSourceManager[MaxioResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint = ENDPOINTS[inputs.schema_name]

        resource = maxio_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint.primary_keys,
            column_hints=resource.column_hints,
        )

        if endpoint.partition_keys:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "week"
            response.partition_keys = endpoint.partition_keys

        return response

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAXIO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Maxio",
            caption=(
                "Connect your Maxio Advanced Billing site to pull customers, subscriptions, "
                "invoices, products, components, coupons, and billing events into the PostHog "
                "Data warehouse. Generate an API key under **Config** > **Integrations** > "
                "**API keys** in your Maxio site."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/maxio",
            iconPath="/static/services/maxio.png",
            keywords=["billing", "subscriptions", "revenue", "chargify", "advanced billing", "saasoptics"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Site subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        caption="The subdomain of your Maxio site, e.g. `acme` for `acme.chargify.com`.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Hosting region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (chargify.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (ebilling.maxio.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )
