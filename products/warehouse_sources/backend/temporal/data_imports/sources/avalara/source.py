from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara import (
    AvalaraResumeConfig,
    avalara_source,
    validate_credentials as validate_avalara_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.avalara import (
    AvalaraSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AvalaraSource(ResumableSource[AvalaraSourceConfig, AvalaraResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.avalara.com/api-reference/avatax/rest/v2/methods/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AVALARA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Avalara authentication failed. Please check your account ID and license key.",
            "403 Client Error: Forbidden": "Avalara denied access. Please check that your license key has permission for this company's data.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AVALARA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Avalara AvaTax",
            caption="""Connect your Avalara AvaTax account to pull tax transactions, companies, nexus, customers and exemption certificates into the PostHog Data warehouse.

Use your AvaTax account ID and a license key (found under Settings > License and API Keys). Generating a new license key immediately revokes the previous one. Sandbox and production credentials only work against their matching environment, so pick the one your account was created in.""",
            docsUrl="https://posthog.com/docs/cdp/sources/avalara",
            iconPath="/static/services/avalara.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["avatax", "tax", "sales tax", "sales-tax"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="license_key",
                        label="License key",
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
        config: AvalaraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AvalaraSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_avalara_credentials(config.account_id, config.license_key, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AvalaraResumeConfig]:
        return ResumableSourceManager[AvalaraResumeConfig](inputs, AvalaraResumeConfig)

    def source_for_pipeline(
        self,
        config: AvalaraSourceConfig,
        resumable_source_manager: ResumableSourceManager[AvalaraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return avalara_source(
            account_id=config.account_id,
            license_key=config.license_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
