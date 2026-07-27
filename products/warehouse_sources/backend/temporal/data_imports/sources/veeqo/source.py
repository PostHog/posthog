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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.veeqo import VeeqoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.veeqo import (
    VeeqoResumeConfig,
    validate_credentials as validate_veeqo_credentials,
    veeqo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VeeqoSource(ResumableSource[VeeqoSourceConfig, VeeqoResumeConfig]):
    # Veeqo's API is unversioned (no version path segment, header, or param).
    api_docs_url = "https://developers.veeqo.com/api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VEEQO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VEEQO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Veeqo",
            caption="""Enter your Veeqo API key to automatically pull your Veeqo inventory, order and shipping data into the PostHog Data warehouse.

You can find your API key in your Veeqo account under **Settings > Users**, on your user's profile. Veeqo support must enable API access for your account before the key appears there — contact them if you don't see it.

The API key gives full account access, so store it securely.
""",
            iconPath="/static/services/veeqo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/veeqo",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Veeqo API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.veeqo.com": (
                "Veeqo rejected the API key. Check the key in your Veeqo account settings and reconnect — "
                "Veeqo support must enable API access before a key works."
            ),
            "403 Client Error: Forbidden for url: https://api.veeqo.com": (
                "The Veeqo API key does not have access to this resource. Check the key and try again."
            ),
        }

    def get_schemas(
        self,
        config: VeeqoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: VeeqoSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_veeqo_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VeeqoResumeConfig]:
        return ResumableSourceManager[VeeqoResumeConfig](inputs, VeeqoResumeConfig)

    def source_for_pipeline(
        self,
        config: VeeqoSourceConfig,
        resumable_source_manager: ResumableSourceManager[VeeqoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return veeqo_source(
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
