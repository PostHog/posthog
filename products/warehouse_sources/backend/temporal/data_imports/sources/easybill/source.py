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
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.easybill import (
    EasybillResumeConfig,
    easybill_source,
    validate_credentials as validate_easybill_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EasybillSource(ResumableSource[EasybillSourceConfig, EasybillResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # easybill's REST API has a single, fixed `/rest/v1` base path with no documented version
    # header, query param, or changelog — there is nothing to pin.
    api_docs_url = "https://www.easybill.de/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EASYBILL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EASYBILL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="easybill",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Enter your easybill API key to sync your invoices, customers and accounting records into the PostHog data warehouse. Generate a key from your easybill account under **username menu > Profil und Einstellungen**.",
            iconPath="/static/services/easybill.png",
            docsUrl="https://posthog.com/docs/cdp/sources/easybill",
            keywords=["invoicing", "billing", "accounting", "germany", "gobd"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.easybill.de": "Your easybill API key is invalid or has expired. Generate a new key from your easybill account and reconnect.",
            "403 Client Error: Forbidden for url: https://api.easybill.de": "Your easybill API key does not have access to this data. Check the key's permissions in your easybill account and reconnect.",
        }

    def get_schemas(
        self,
        config: EasybillSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: EasybillSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_easybill_credentials(config.api_key):
            return True, None

        return False, "Invalid easybill API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EasybillResumeConfig]:
        return ResumableSourceManager[EasybillResumeConfig](inputs, EasybillResumeConfig)

    def source_for_pipeline(
        self,
        config: EasybillSourceConfig,
        resumable_source_manager: ResumableSourceManager[EasybillResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return easybill_source(
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
