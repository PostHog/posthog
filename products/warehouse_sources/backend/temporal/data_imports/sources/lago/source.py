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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LagoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.lago import (
    HOST_NOT_ALLOWED_ERROR,
    LagoResumeConfig,
    lago_source,
    validate_credentials as validate_lago_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LagoSource(ResumableSource[LagoSourceConfig, LagoResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAGO

    @property
    def connection_host_fields(self) -> list[str]:
        # `api_url` is where the stored API key is sent; retargeting it must re-require the key.
        return ["api_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Lago API key. Please generate a new key and reconnect.",
            "403 Client Error": "Your Lago API key lacks the required permissions. Please check the key and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Lago API URL is not allowed. Please use a publicly reachable host.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lago.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LagoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
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
        self, config: LagoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_lago_credentials(config.api_url, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LagoResumeConfig]:
        return ResumableSourceManager[LagoResumeConfig](inputs, LagoResumeConfig)

    def source_for_pipeline(
        self,
        config: LagoSourceConfig,
        resumable_source_manager: ResumableSourceManager[LagoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lago_source(
            api_url=config.api_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LAGO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Lago",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Lago API key to pull your billing data into the PostHog Data warehouse.

You can create an API key in the Lago dashboard under **Developers > API keys**.

Self-hosted Lago users should set the API URL to their own Lago host (for example `https://billing.example.com`). Leave it blank to use Lago Cloud.""",
            iconPath="/static/services/lago.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lago",
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
                        name="api_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.getlago.com",
                        secret=False,
                    ),
                ],
            ),
        )
