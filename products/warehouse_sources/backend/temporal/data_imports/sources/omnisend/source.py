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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OmnisendSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    OmnisendResumeConfig,
    omnisend_source,
    validate_credentials as validate_omnisend_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OmnisendSource(ResumableSource[OmnisendSourceConfig, OmnisendResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OMNISEND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OMNISEND,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Omnisend",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Omnisend API key to automatically pull your Omnisend data into the PostHog Data warehouse.

You can create an API key in your [Omnisend account settings](https://app.omnisend.com/settings/integrations/api-keys).
""",
            iconPath="/static/services/omnisend.png",
            docsUrl="https://posthog.com/docs/cdp/sources/omnisend",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OmnisendSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(fields := INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(fields),
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OmnisendSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_omnisend_credentials(config.api_key)
        if is_valid:
            return True, None

        if status_code in (401, 403):
            return False, "Invalid Omnisend API key"

        return False, "Could not connect to Omnisend with the provided API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Omnisend API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Omnisend API key does not have the required permissions. Please check the key and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OmnisendResumeConfig]:
        return ResumableSourceManager[OmnisendResumeConfig](inputs, OmnisendResumeConfig)

    def source_for_pipeline(
        self,
        config: OmnisendSourceConfig,
        resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return omnisend_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
