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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RecurlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.recurly import (
    RecurlyResumeConfig,
    recurly_source,
    validate_credentials as validate_recurly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import (
    INCREMENTAL_FIELDS,
    RECURLY_ENDPOINTS,
    RECURLY_PARTITION_KEY,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RecurlySource(ResumableSource[RecurlySourceConfig, RecurlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2021-02-25",)
    default_version = "v2021-02-25"
    api_docs_url = "https://recurly.com/developers/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECURLY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Recurly rejected the API key. Generate a new private API key in Recurly and reconnect.",
            "403 Client Error: Forbidden": "The Recurly API key does not have access to this resource. Check the key's permissions and reconnect.",
        }

    def get_schemas(
        self,
        config: RecurlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(name, []),
            )
            for name, endpoint in RECURLY_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: RecurlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_recurly_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RecurlyResumeConfig]:
        return ResumableSourceManager[RecurlyResumeConfig](inputs, RecurlyResumeConfig)

    def source_for_pipeline(
        self,
        config: RecurlySourceConfig,
        resumable_source_manager: ResumableSourceManager[RecurlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = recurly_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"],
            column_hints=resource.column_hints,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="week",
            partition_keys=[RECURLY_PARTITION_KEY],
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RECURLY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Recurly",
            caption=(
                "Connect your Recurly site using a **private API key**. Create one in Recurly under "
                "**Integrations > API Credentials**. The key authenticates to a single Recurly site, so "
                "pick the region that matches it."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/recurly",
            iconPath="/static/services/recurly.png",
            fields=cast(
                list[FieldType],
                [
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
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (v3.recurly.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (v3.eu.recurly.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
