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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harvest import (
    HarvestSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.harvest import (
    HarvestResumeConfig,
    harvest_source,
    validate_credentials as validate_harvest_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    HARVEST_API_VERSION,
    HARVEST_SUPPORTED_VERSIONS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HarvestSource(ResumableSource[HarvestSourceConfig, HarvestResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = HARVEST_SUPPORTED_VERSIONS
    default_version = HARVEST_API_VERSION
    api_docs_url = "https://help.getharvest.com/api-v2/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARVEST

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.harvestapp.com": "Your Harvest access token or account ID is invalid. Create a new personal access token in Harvest, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.harvestapp.com": "Your Harvest user does not have permission to read this data. Some tables need an administrator or manager role, so check the user's permissions and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HarvestSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)

    def validate_credentials(
        self,
        config: HarvestSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status = validate_harvest_credentials(
            config.account_id, config.access_token, self.resolve_api_version(api_version)
        )
        if ok:
            return True, None
        if status is None:
            return False, "Could not reach Harvest to validate the credentials. Check your connection and try again."
        if status == 403:
            return (
                False,
                "This Harvest user does not have permission to read this data. Check the user's role and reconnect.",
            )
        return False, "Invalid Harvest account ID or access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HarvestResumeConfig]:
        return ResumableSourceManager[HarvestResumeConfig](inputs, HarvestResumeConfig)

    def source_for_pipeline(
        self,
        config: HarvestSourceConfig,
        resumable_source_manager: ResumableSourceManager[HarvestResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return harvest_source(
            account_id=config.account_id,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HARVEST,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Harvest",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["time tracking", "timesheets", "invoicing"],
            caption="""Enter your Harvest account ID and a personal access token to sync your time tracking and invoicing data into the PostHog Data warehouse.

Create a token at [id.getharvest.com/developers](https://id.getharvest.com/developers), which shows the account ID alongside it. The token inherits the permissions of the user who created it, so connect a user who can see the data you want to sync. Listing users and roles needs an administrator.""",
            iconPath="/static/services/harvest.png",
            docsUrl="https://posthog.com/docs/cdp/sources/harvest",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
