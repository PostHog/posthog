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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WindmillSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    WINDMILL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill import (
    WindmillResumeConfig,
    validate_credentials as validate_windmill_credentials,
    windmill_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WindmillSource(ResumableSource[WindmillSourceConfig, WindmillResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WINDMILL

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to whatever host `host` points at, so retargeting it must
        # re-require the token (prevents exfiltrating the stored bearer token to another host).
        return ["host"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WINDMILL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Windmill",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Windmill instance URL, workspace ID, and API token to sync your Windmill data into the PostHog Data warehouse.

Create a personal API token in your Windmill account under **User settings → Tokens**. For cloud, your instance URL is `https://app.windmill.dev`; for self-hosted, use your own instance URL.

The audit logs table requires a workspace-admin token and is a Windmill Enterprise Edition feature.""",
            iconPath="/static/services/windmill.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/windmill",
            keywords=["workflow", "automation", "jobs", "scripts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://app.windmill.dev",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="workspace",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-workspace",
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
            "401 Client Error": "Invalid Windmill API token. Create a new token in your Windmill user settings and reconnect.",
            "403 Client Error": "Your Windmill API token lacks permission for this workspace or resource. Check the token's access and reconnect.",
        }

    def get_schemas(
        self,
        config: WindmillSourceConfig,
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
                should_sync_default=WINDMILL_ENDPOINTS[endpoint].should_sync_default,
                description=WINDMILL_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: WindmillSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_windmill_credentials(config.api_token, config.host, config.workspace, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WindmillResumeConfig]:
        return ResumableSourceManager[WindmillResumeConfig](inputs, WindmillResumeConfig)

    def source_for_pipeline(
        self,
        config: WindmillSourceConfig,
        resumable_source_manager: ResumableSourceManager[WindmillResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return windmill_source(
            api_token=config.api_token,
            base_url=config.host,
            workspace=config.workspace,
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
