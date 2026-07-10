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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StatuspageSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage import (
    StatuspageResumeConfig,
    statuspage_source,
    validate_credentials as validate_statuspage_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StatuspageSource(ResumableSource[StatuspageSourceConfig, StatuspageResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STATUSPAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STATUSPAGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Statuspage",
            caption=(
                "Sync your Atlassian Statuspage data. Create a key under "
                "**[Manage account > API info](https://manage.statuspage.io/account/api-info)** and paste it below. "
                "The key has organization-wide management access; no extra scopes are required."
            ),
            iconPath="/static/services/statuspage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/statuspage",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Statuspage API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Statuspage API key. Please check your API key and reconnect.",
            "403 Client Error": "Your Statuspage API key lacks the required permissions. Please check the key and reconnect.",
            "Could not authenticate": "Your Statuspage API key is invalid or expired. Please reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StatuspageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Statuspage has no server-side updated_after/since filter on any list endpoint, so
                # every schema is full-refresh only.
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: StatuspageSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_statuspage_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StatuspageResumeConfig]:
        return ResumableSourceManager[StatuspageResumeConfig](inputs, StatuspageResumeConfig)

    def source_for_pipeline(
        self,
        config: StatuspageSourceConfig,
        resumable_source_manager: ResumableSourceManager[StatuspageResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return statuspage_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
