from typing import Optional, cast

from products.warehouse_sources.sources.cin7._config import Cin7SourceConfig
from products.warehouse_sources.sources.cin7.cin7 import (
    Cin7ResumeConfig,
    cin7_source,
    validate_credentials as validate_cin7_credentials,
)
from products.warehouse_sources.sources.cin7.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class Cin7Source(ResumableSource[Cin7SourceConfig, Cin7ResumeConfig]):
    # Cin7 Core publishes no SDK or script tag.
    codebase_detection = detect(env=("^CIN7_",))

    lists_tables_without_credentials = True  # get_schemas reads a static catalog, so public docs can list the tables

    # The API version is the `/ExternalApi/v2` path segment.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://dearinventory.docs.apiary.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIN7

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        rejected = "Cin7 Core rejected the account ID or application key. Copy both values from Integrations > API in Cin7 Core, then reconnect the source."
        return {
            "401 Client Error: Unauthorized for url: https://inventory.dearsystems.com": rejected,
            "403 Client Error: Forbidden for url: https://inventory.dearsystems.com": rejected,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.cin7.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Cin7SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: Cin7SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cin7_credentials(config.account_id.strip(), config.application_key.strip())

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Cin7ResumeConfig]:
        return ResumableSourceManager[Cin7ResumeConfig](inputs, Cin7ResumeConfig)

    def source_for_pipeline(
        self,
        config: Cin7SourceConfig,
        resumable_source_manager: ResumableSourceManager[Cin7ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cin7_source(
            account_id=config.account_id.strip(),
            application_key=config.application_key.strip(),
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
            name=ExternalDataSourceType.CIN7,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Cin7",
            keywords=["cin7 core", "dear inventory", "dear systems", "inventory"],
            caption=(
                "Import products, stock levels, customers, suppliers, sales and purchases from Cin7 Core "
                "(formerly DEAR Inventory). This source does not support Cin7 Omni.\n\n"
                "In Cin7 Core, go to **Integrations > API** and create an API application. "
                "Copy the **Account ID** and the **Application key** below."
            ),
            iconPath="/static/services/cin7.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cin7",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="application_key",
                        label="Application key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
