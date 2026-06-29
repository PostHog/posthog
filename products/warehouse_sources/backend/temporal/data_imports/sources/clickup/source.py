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
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.clickup import (
    ClickUpResumeConfig,
    clickup_source,
    validate_credentials as validate_clickup_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import (
    CLICKUP_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClickUpSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClickUpSource(ResumableSource[ClickUpSourceConfig, ClickUpResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKUP

    @property
    def connection_host_fields(self) -> list[str]:
        # `workspace_id` selects which ClickUp workspace the stored API token is used against.
        # Editing it on an existing source must force the token to be re-entered — otherwise an
        # editor could retarget the preserved token at another workspace it can access.
        return ["workspace_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLICK_UP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="ClickUp",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ClickUp personal API token to pull your ClickUp data into the PostHog Data warehouse.

You can generate a personal token (starts with `pk_`) under **Settings → Apps** in ClickUp.

The **Workspace ID** is the numeric ID in your ClickUp URL: `https://app.clickup.com/{workspace_id}/...`.
""",
            iconPath="/static/services/clickup.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/clickup",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="9008123456",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clickup.com": "Your ClickUp API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.clickup.com": "Your ClickUp API token does not have access to this resource. Check the token permissions and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClickUpSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=CLICKUP_ENDPOINTS[endpoint].supports_incremental,
                supports_append=False,
                incremental_fields=CLICKUP_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ClickUpSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_clickup_credentials(config.api_key, config.workspace_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClickUpResumeConfig]:
        return ResumableSourceManager[ClickUpResumeConfig](inputs, ClickUpResumeConfig)

    def source_for_pipeline(
        self,
        config: ClickUpSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clickup_source(
            api_key=config.api_key,
            workspace_id=config.workspace_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
