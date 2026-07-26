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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plunk import PlunkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.plunk import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    PlunkResumeConfig,
    plunk_source,
    validate_credentials as validate_plunk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlunkSource(ResumableSource[PlunkSourceConfig, PlunkResumeConfig]):
    # Plunk's data endpoints carry no version prefix (only the public send/track endpoints
    # are versioned), so the source is unversioned.
    api_docs_url = "https://docs.useplunk.com/api-reference/overview"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLUNK

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored secret key is sent; retargeting it must re-require the key.
        return ["base_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Plunk secret API key. Copy the sk_* key from your Plunk project settings and reconnect.",
            "403 Client Error": "Plunk rejected the request. Check that your project is active and your account email is verified.",
            HOST_NOT_ALLOWED_ERROR: "The Plunk API URL is not allowed. Please use a publicly reachable host.",
            HTTP_NOT_ALLOWED_ERROR: "The Plunk API URL must use HTTPS. Please update the API URL to use https://.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PlunkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # No Plunk list endpoint accepts a server-side timestamp filter, so every
        # endpoint is full-refresh only (INCREMENTAL_FIELDS is empty per endpoint).
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: PlunkSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_plunk_credentials(config.base_url, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlunkResumeConfig]:
        return ResumableSourceManager[PlunkResumeConfig](inputs, PlunkResumeConfig)

    def source_for_pipeline(
        self,
        config: PlunkSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlunkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return plunk_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLUNK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Plunk",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["useplunk", "email marketing"],
            caption="""Enter your Plunk secret API key to pull your contacts, campaigns, templates, and segments into the PostHog Data warehouse.

You can find your secret API key (it starts with `sk_`) in your Plunk project settings under **Project Settings > API Keys**. The public key (`pk_`) cannot read data.

Self-hosted users should set the API URL to their own Plunk API host (for example `https://plunk-api.example.com`). Leave it blank to use the hosted Plunk (`https://next-api.useplunk.com`).""",
            iconPath="/static/services/plunk.png",
            docsUrl="https://posthog.com/docs/cdp/sources/plunk",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://next-api.useplunk.com",
                        secret=False,
                    ),
                ],
            ),
        )
