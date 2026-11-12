from typing import Optional, cast

from products.warehouse_sources.sources.holded._config import HoldedSourceConfig
from products.warehouse_sources.sources.holded.holded import HoldedResumeConfig, check_credentials, holded_source
from products.warehouse_sources.sources.holded.settings import ENDPOINTS, INCREMENTAL_FIELDS
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

INVALID_KEY_MESSAGE = (
    "Holded refused this API key. Check that you copied the whole key, and that it has the "
    "`account:info.read` permission."
)


@SourceRegistry.register
class HoldedSource(ResumableSource[HoldedSourceConfig, HoldedResumeConfig]):
    # Holded publishes no official SDK, so only the environment variable names give it away.
    codebase_detection = detect(env=("^HOLDED_",))

    lists_tables_without_credentials = True
    # The v1 API (`/api/invoicing/v1`, `/api/crm/v1`, ...) sends a sunset date of 2027-07-01.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.holded.com/en-us/developers/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOLDED

    @property
    def credential_auth_type(self) -> str:
        # The scaffold had no fields, so `facade/credential_auth_types.py` froze "credentials" for
        # this kind. One secret field derives "token", and changing a frozen default needs a data
        # migration, so keep the frozen value.
        return "credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.holded.com": "Holded rejected your API key. Create a new key in Holded under Settings > API, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.holded.com": "Holded refused access with your API key. The key was revoked, or it has no read permission for this table. Check the key in Holded, then reconnect the source or deselect the table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.holded.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HoldedSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: HoldedSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        valid, status = check_credentials(config.api_key, self.resolve_api_version(api_version))
        if valid:
            return True, None
        if status in (401, 403):
            return False, INVALID_KEY_MESSAGE
        if status == 429:
            return False, "Holded rate limited the request. Wait a minute, then try again."
        return False, "Couldn't connect to Holded. Try again, and if it keeps happening contact support."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HoldedResumeConfig]:
        return ResumableSourceManager[HoldedResumeConfig](inputs, HoldedResumeConfig)

    def source_for_pipeline(
        self,
        config: HoldedSourceConfig,
        resumable_source_manager: ResumableSourceManager[HoldedResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return holded_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOLDED,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Holded",
            caption=(
                "Sync invoices, purchases, payments, contacts, accounting, CRM, project and team data from Holded.\n\n"
                "Each sync reads every selected table in full and uses calls from your Holded monthly API quota, "
                "so select only the tables you need."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/holded",
            iconPath="/static/warehouse-sources/holded/icon.png",
            keywords=["visma"],
            releaseStatus=ReleaseStatus.BETA,
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
                        caption=(
                            "Create a key in Holded under **Settings > API**. Give it read permission for the "
                            "tables you want to sync, and `account:info.read` so PostHog can check the key."
                        ),
                    ),
                ],
            ),
        )
