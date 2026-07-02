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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GuruSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru import (
    GuruResumeConfig,
    guru_source,
    validate_credentials as validate_guru_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GuruSource(ResumableSource[GuruSourceConfig, GuruResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GURU

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.guru.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.getguru.com": "Guru authentication failed. Please check your username and API token.",
            "403 Client Error: Forbidden for url: https://api.getguru.com": "Guru denied access. Please check that your API token has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GURU,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Guru",
            caption="""Enter your Guru API credentials to pull your Guru knowledge base data into the PostHog Data warehouse.

You authenticate with your Guru account email and a user API token. A Guru admin can generate user tokens from [Settings > Apps and integrations > API access](https://app.getguru.com/settings/integrations/api-access). Use a user token rather than a collection token — collection tokens are read-only and scoped to a single collection.""",
            iconPath="/static/services/guru.png",
            docsUrl="https://posthog.com/docs/cdp/sources/guru",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Username (email)",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="user@company.com",
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

    def get_schemas(
        self,
        config: GuruSourceConfig,
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
        self, config: GuruSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_guru_credentials(config.username, config.api_token):
            return True, None

        return False, "Invalid Guru API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GuruResumeConfig]:
        return ResumableSourceManager[GuruResumeConfig](inputs, GuruResumeConfig)

    def source_for_pipeline(
        self,
        config: GuruSourceConfig,
        resumable_source_manager: ResumableSourceManager[GuruResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return guru_source(
            username=config.username,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
