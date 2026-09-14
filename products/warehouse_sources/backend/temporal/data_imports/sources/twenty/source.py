from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.twenty import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    TwentyResumeConfig,
    twenty_source,
    validate_credentials as validate_twenty_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwentySource(ResumableSource[TwentySourceConfig, TwentyResumeConfig]):
    api_docs_url = "https://docs.twenty.com/developers/extend/api"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWENTY

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent; retargeting it must re-require the key.
        return ["base_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **auth_non_retryable_errors(service="Twenty"),
            HOST_NOT_ALLOWED_ERROR: "The Twenty instance URL is not allowed. Please use a publicly reachable host.",
            HTTP_NOT_ALLOWED_ERROR: "The Twenty instance URL must use HTTPS. Please update the instance URL to use https://.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TwentySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TwentySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_twenty_credentials(config.base_url, config.api_key, team_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwentyResumeConfig]:
        return ResumableSourceManager[TwentyResumeConfig](inputs, TwentyResumeConfig)

    def source_for_pipeline(
        self,
        config: TwentySourceConfig,
        resumable_source_manager: ResumableSourceManager[TwentyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return twenty_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWENTY,
            category=DataWarehouseSourceCategory.CRM,
            label="Twenty",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["crm", "sales", "open source", "salesforce"],
            caption="""Enter your Twenty API key to pull your CRM data into the PostHog Data warehouse.

Generate an API key in Twenty under **Settings > API & Webhooks > + Create key**. Copy it immediately, it's only shown once.

Self-hosted users should set the instance URL to their own Twenty host (for example `https://twenty.example.com`). Leave it blank to use Twenty Cloud (`https://api.twenty.com`).""",
            iconPath="/static/services/twenty.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/twenty",
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
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.twenty.com",
                        secret=False,
                    ),
                ],
            ),
        )
