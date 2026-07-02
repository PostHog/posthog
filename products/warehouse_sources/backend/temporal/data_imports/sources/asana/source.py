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
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.asana import (
    AsanaResumeConfig,
    asana_source,
    validate_credentials as validate_asana_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AsanaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AsanaSource(ResumableSource[AsanaSourceConfig, AsanaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASANA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Asana",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter an Asana personal access token to pull your Asana data into the PostHog Data warehouse.

You can create a personal access token from the [developer console](https://app.asana.com/0/my-apps).

Grant these read scopes so every table can sync:
- `workspaces:read`
- `users:read`
- `projects:read`
- `tasks:read`
- `tags:read`
- `teams:read`
- `custom_fields:read`
""",
            iconPath="/static/services/asana.png",
            docsUrl="https://posthog.com/docs/cdp/sources/asana",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="1/12345...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.asana.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.asana.com": "Your Asana token is invalid or expired. Please generate a new personal access token and reconnect.",
            "403 Client Error: Forbidden for url: https://app.asana.com": "Your Asana token is missing the required read scopes. Please grant the scopes listed in the connection form and reconnect.",
        }

    def get_schemas(
        self,
        config: AsanaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AsanaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_asana_credentials(config.access_token):
            return True, None

        return False, "Invalid Asana personal access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AsanaResumeConfig]:
        return ResumableSourceManager[AsanaResumeConfig](inputs, AsanaResumeConfig)

    def source_for_pipeline(
        self,
        config: AsanaSourceConfig,
        resumable_source_manager: ResumableSourceManager[AsanaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return asana_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
