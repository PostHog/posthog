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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omni import OmniSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.omni import (
    OmniResumeConfig,
    get_endpoint_permissions as get_omni_endpoint_permissions,
    omni_source,
    validate_credentials as validate_omni_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OmniSource(ResumableSource[OmniSourceConfig, OmniResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.omni.co/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OMNI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Omni API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Omni API key does not have the required permissions. Please check the key's access and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.omni.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OmniSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OmniSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_omni_credentials(config.host, config.api_key, team_id, schema_name)

    def get_endpoint_permissions(
        self, config: OmniSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_omni_endpoint_permissions(config.host, config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OmniResumeConfig]:
        return ResumableSourceManager[OmniResumeConfig](inputs, OmniResumeConfig)

    def source_for_pipeline(
        self,
        config: OmniSourceConfig,
        resumable_source_manager: ResumableSourceManager[OmniResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return omni_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OMNI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Omni Analytics",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Sync documents, folders, connections, schedules, users, and user groups from your Omni instance.\n\nUse an **Organization API key** for full coverage (**Settings > API access**) — Personal Access Tokens only see content the token owner can access, and can't read the Users or User groups tables at all.",
            docsUrl="https://posthog.com/docs/cdp/sources/omni",
            iconPath="/static/services/omni.png",
            keywords=["bi", "business intelligence"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-company.omniapp.co",
                        secret=False,
                    ),
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
        )
