from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.bigeye import (
    WORKSPACE_ID_REQUIRED_MESSAGE,
    BigeyeResumeConfig,
    bigeye_source,
    validate_credentials as validate_bigeye_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigeye import BigeyeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BigeyeSource(ResumableSource[BigeyeSourceConfig, BigeyeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Bigeye's REST API has no dated or numbered version token (see docs.bigeye.com/reference) —
    # every path is a bare `/api/v1/...` that has never changed.
    api_docs_url = "https://docs.bigeye.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BIGEYE

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` is where the stored API key is sent; retargeting it must re-require the key.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Bigeye API key. Please generate a new key and reconnect.",
            "403 Client Error": "Your Bigeye API key does not have permission for this data. Please check the key's role and try again.",
            WORKSPACE_ID_REQUIRED_MESSAGE: (
                "This Bigeye account has more than one workspace. Please set the Workspace ID field and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bigeye.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BigeyeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BigeyeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bigeye_credentials(config.api_key, config.host, config.workspace_id, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BigeyeResumeConfig]:
        return ResumableSourceManager[BigeyeResumeConfig](inputs, BigeyeResumeConfig)

    def source_for_pipeline(
        self,
        config: BigeyeSourceConfig,
        resumable_source_manager: ResumableSourceManager[BigeyeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bigeye_source(
            api_key=config.api_key,
            host=config.host,
            workspace_id=config.workspace_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BIGEYE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bigeye",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Bigeye API key to pull your data observability metadata into the PostHog Data warehouse.

Generate a Personal or Agent API key from **Advanced Settings** in your Bigeye workspace. The key inherits your Bigeye role's access (view, edit, or manage).""",
            iconPath="/static/services/bigeye.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bigeye",
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
                        name="host",
                        label="Bigeye host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="app.bigeye.com",
                        caption="Leave blank unless your organization uses a self-hosted or regional Bigeye instance.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="",
                        caption="Only needed if your Bigeye account has more than one workspace. Find it in workspace settings.",
                        secret=False,
                    ),
                ],
            ),
        )
