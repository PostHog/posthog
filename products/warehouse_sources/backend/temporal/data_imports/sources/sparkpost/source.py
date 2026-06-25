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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SparkPostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIMITED_RETENTION_ENDPOINTS,
    SPARKPOST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    SparkPostResumeConfig,
    sparkpost_source,
    validate_credentials as validate_sparkpost_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SparkPostSource(ResumableSource[SparkPostSourceConfig, SparkPostResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPARKPOST

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the host derived from `region`, so changing the region must
        # re-require the key rather than reusing it against a different host.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPARK_POST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SparkPost",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden for now: the implementation follows the public SparkPost docs but its
            # end-to-end sync behaviour hasn't been exercised against a live account yet.
            unreleasedSource=True,
            caption="""Connect your SparkPost account to sync message events, suppression lists, recipient lists, templates, sending domains, subaccounts, and webhooks into the PostHog Data warehouse.

Create an API key in your [SparkPost account settings](https://app.sparkpost.com/account/api-keys) (or the EU console at app.eu.sparkpost.com). Grant the read permissions for the data you want to sync, for example:
- `Events: Read-only`
- `Suppression Lists: Read-only`
- `Recipient Lists: Read-only`
- `Templates: Read-only`
- `Sending Domains: Read-only`
- `Subaccounts: Read-only`
- `Webhooks: Read-only`

SparkPost runs independent US and EU stacks that do not share data — pick the region your account is on. Message events are retained for 10 days, so the initial sync of events can only reach back that far.""",
            iconPath="/static/services/sparkpost.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sparkpost",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.sparkpost.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.sparkpost.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="SparkPost API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid SparkPost API key. Generate a valid key and reconnect.",
            "403 Client Error": "Your SparkPost API key is missing the read permissions for this data. Grant the required permissions and reconnect.",
        }

    def get_schemas(
        self,
        config: SparkPostSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=SPARKPOST_ENDPOINTS[endpoint].supports_incremental,
                supports_append=SPARKPOST_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=SPARKPOST_ENDPOINTS[endpoint].should_sync_default,
                description=(
                    "Only the last 10 days are available on initial sync (SparkPost event retention)"
                    if endpoint in LIMITED_RETENTION_ENDPOINTS
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SparkPostSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_sparkpost_credentials(config.region, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SparkPostResumeConfig]:
        return ResumableSourceManager[SparkPostResumeConfig](inputs, SparkPostResumeConfig)

    def source_for_pipeline(
        self,
        config: SparkPostSourceConfig,
        resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sparkpost_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
