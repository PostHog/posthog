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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SentineloneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone import (
    HOST_NOT_ALLOWED_ERROR,
    SentinelOneResumeConfig,
    sentinelone_source,
    validate_credentials as validate_sentinelone_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SentineloneSource(ResumableSource[SentineloneSourceConfig, SentinelOneResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENTINELONE

    @property
    def connection_host_fields(self) -> list[str]:
        # `console_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["console_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SENTINELONE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="SentinelOne",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SentinelOne management console URL and an API token to pull your SentinelOne data into the PostHog Data warehouse.

You can generate an API token in your management console under **My User > Actions > API Token Operations**. The token inherits your user's role and scope (account, site, or group), which determines which records sync.
""",
            iconPath="/static/services/sentinelone.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sentinelone",
            keywords=["s1", "edr", "endpoint security"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="console_url",
                        label="Console URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-tenant.sentinelone.net",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired SentinelOne API token. Please generate a new token in your management console and reconnect.",
            "403 Client Error": "Your SentinelOne API token's user lacks the required permissions. Please check the user's role and scope and try again.",
            HOST_NOT_ALLOWED_ERROR: "The SentinelOne console URL is not allowed. Please use your organization's management console URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SentineloneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SentineloneSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sentinelone_credentials(config.console_url, config.api_token, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SentinelOneResumeConfig]:
        return ResumableSourceManager[SentinelOneResumeConfig](inputs, SentinelOneResumeConfig)

    def source_for_pipeline(
        self,
        config: SentineloneSourceConfig,
        resumable_source_manager: ResumableSourceManager[SentinelOneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sentinelone_source(
            console_url=config.console_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
