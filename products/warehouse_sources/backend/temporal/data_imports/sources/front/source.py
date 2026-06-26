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
from products.warehouse_sources.backend.temporal.data_imports.sources.front.front import (
    FrontResumeConfig,
    front_source,
    validate_credentials as validate_front_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import (
    ENDPOINTS,
    FRONT_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FrontSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FrontSource(ResumableSource[FrontSourceConfig, FrontResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRONT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRONT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Front",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Front API token to sync your Front data into the PostHog Data warehouse.

You can create an API token in your [Front settings](https://app.frontapp.com/settings/tools/api) under **Developers > API tokens**.

Grant read scopes for the resources you want to sync (e.g. `shared_resources:read`, `contacts:read`, `tags:read`).""",
            iconPath="/static/services/front.png",
            docsUrl="https://posthog.com/docs/cdp/sources/front",
            fields=cast(
                list[FieldType],
                [
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.front.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Front API token. Please reconnect with a valid token.",
            "403 Client Error": "Your Front API token does not have the required scope for this resource.",
        }

    def get_schemas(
        self,
        config: FrontSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=FRONT_ENDPOINTS[endpoint].supports_incremental,
                supports_append=FRONT_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Only syncs the last 365 days on initial sync" if endpoint == "events" else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FrontSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if schema_name is None:
            # Source-create probe: any non-401 response means the token is genuine. Accept 403 here
            # so a scope-limited token still connects (the user grants scopes per resource).
            return validate_front_credentials(config.api_token, "/teammates", require_scope=False)

        endpoint_config = FRONT_ENDPOINTS.get(schema_name)
        path = endpoint_config.path if endpoint_config else "/teammates"
        return validate_front_credentials(config.api_token, path, require_scope=True)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FrontResumeConfig]:
        return ResumableSourceManager[FrontResumeConfig](inputs, FrontResumeConfig)

    def source_for_pipeline(
        self,
        config: FrontSourceConfig,
        resumable_source_manager: ResumableSourceManager[FrontResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return front_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
