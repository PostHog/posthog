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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RollbarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar import (
    RollbarResumeConfig,
    rollbar_source,
    validate_credentials as validate_rollbar_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RollbarSource(ResumableSource[RollbarSourceConfig, RollbarResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("1",)
    default_version = "1"
    api_docs_url = "https://docs.rollbar.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROLLBAR

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.rollbar.com": "Rollbar authentication failed. Please check your project access token.",
            "403 Client Error: Forbidden for url: https://api.rollbar.com": "Rollbar denied access. Please check that your project access token has the read scope.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROLLBAR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Rollbar",
            caption="""Enter your Rollbar project access token to pull your Rollbar error data into the PostHog Data warehouse.

You can find or create a project access token in your Rollbar project under Settings > Project Access Tokens. A token with the `read` scope is sufficient. Each PostHog source connects to one Rollbar project — add one source per project.""",
            iconPath="/static/services/rollbar.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rollbar",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Project access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: RollbarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: RollbarSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_rollbar_credentials(config.access_token):
            return True, None

        return False, "Invalid Rollbar project access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RollbarResumeConfig]:
        return ResumableSourceManager[RollbarResumeConfig](inputs, RollbarResumeConfig)

    def source_for_pipeline(
        self,
        config: RollbarSourceConfig,
        resumable_source_manager: ResumableSourceManager[RollbarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rollbar_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
