from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sleekplan import (
    SleekplanSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.sleekplan import (
    SleekplanResumeConfig,
    sleekplan_source,
    validate_credentials as validate_sleekplan_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SleekplanSource(ResumableSource[SleekplanSourceConfig, SleekplanResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O -- safe for public docs.
    lists_tables_without_credentials = True
    # Sleekplan has only ever published one API (`/v1`) and documents no version selector, so the
    # framework's unversioned default stands.
    api_docs_url = "https://sleekplan.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLEEKPLAN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Sleekplan API key is invalid or has been revoked. Generate a new key under Settings > Developer and reconnect.",
            "403 Client Error": "Your Sleekplan API key does not have permission to read this data. A key inherits the permissions of the member who created it, so create the key from an account that can see this board.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SleekplanSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY_ENDPOINTS)

    def validate_credentials(
        self,
        config: SleekplanSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sleekplan_credentials(config.api_key, schema_name=schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SleekplanResumeConfig]:
        return ResumableSourceManager[SleekplanResumeConfig](inputs, SleekplanResumeConfig)

    def source_for_pipeline(
        self,
        config: SleekplanSourceConfig,
        resumable_source_manager: ResumableSourceManager[SleekplanResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sleekplan_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SLEEKPLAN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Sleekplan",
            caption="""Enter your Sleekplan API key to sync feedback posts, comments, votes, changelog updates, end users, and survey responses into the PostHog Data warehouse.

Create a key in Sleekplan under **Settings > Developer**. A key inherits the permissions of the member who created it, so create it from an account that can see every board you want to sync.""",
            docsUrl="https://posthog.com/docs/cdp/sources/sleekplan",
            iconPath="/static/services/sleekplan.png",
            keywords=["feedback", "roadmap", "changelog", "nps", "csat"],
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
