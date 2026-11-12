from typing import Optional, cast

from products.warehouse_sources.sources.high_level._config import HighLevelSourceConfig
from products.warehouse_sources.sources.high_level.high_level import (
    HighLevelResumeConfig,
    high_level_source,
    validate_credentials as validate_high_level_credentials,
)
from products.warehouse_sources.sources.high_level.settings import (
    CONTACTS_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
    HIGHLEVEL_API_VERSION_V3,
    INCREMENTAL_FIELDS,
    REQUIRED_SCOPES,
)
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

_HIGHLEVEL_URL = "https://services.leadconnectorhq.com"


@SourceRegistry.register
class HighLevelSource(ResumableSource[HighLevelSourceConfig, HighLevelResumeConfig]):
    codebase_detection = detect(
        npm=("@gohighlevel/api-client",),
        pypi=("gohighlevel-api-client",),
        composer=("gohighlevel/api-client",),
        script_hosts=("widgets.leadconnectorhq.com",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = (HIGHLEVEL_API_VERSION_V3,)
    default_version = HIGHLEVEL_API_VERSION_V3
    api_docs_url = "https://marketplace.gohighlevel.com/docs/Versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HIGHLEVEL

    @property
    def credential_identity_fields(self) -> frozenset[str]:
        # A private integration token belongs to one sub-account, which the location ID names.
        return super().credential_identity_fields | {"location_id"}

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {_HIGHLEVEL_URL}": (
                "HighLevel rejected the private integration token, or the token doesn't have the scope this table "
                "needs. Check the token and its scopes under Settings > Private Integrations in HighLevel, then "
                "update the source."
            ),
            f"403 Client Error: Forbidden for url: {_HIGHLEVEL_URL}": (
                "The private integration token can't read this sub-account. Check that the location ID belongs to "
                "the sub-account where you created the private integration, then update the source."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.high_level.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HighLevelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # Contacts change after they are created, so an append-only table would collect every version.
            merge_only=("contacts",),
            default_incremental_lookback_seconds={"contacts": CONTACTS_INCREMENTAL_LOOKBACK_SECONDS},
        )

    def validate_credentials(
        self,
        config: HighLevelSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_high_level_credentials(
            config.private_integration_token, config.location_id.strip(), schema_name
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HighLevelResumeConfig]:
        return ResumableSourceManager[HighLevelResumeConfig](inputs, HighLevelResumeConfig)

    def source_for_pipeline(
        self,
        config: HighLevelSourceConfig,
        resumable_source_manager: ResumableSourceManager[HighLevelResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return high_level_source(
            token=config.private_integration_token,
            location_id=config.location_id.strip(),
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
        scopes = ", ".join(f"`{scope}`" for scope in REQUIRED_SCOPES)
        return SourceConfig(
            name=ExternalDataSourceType.HIGHLEVEL,
            category=DataWarehouseSourceCategory.CRM,
            keywords=["gohighlevel", "ghl", "leadconnector"],
            label="HighLevel",
            caption=(
                "Sync contacts, opportunities, conversations, payments and more from a HighLevel sub-account. "
                "Create a private integration in the sub-account under **Settings > Private Integrations**, and "
                f"give it the read scopes of the tables you want to sync: {scopes}."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/high-level",
            iconPath="/static/services/high_level.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="private_integration_token",
                        label="Private integration token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pit-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="location_id",
                        label="Location ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ve9EPM428h8vShlRW1KT",
                        caption=(
                            "The ID of the sub-account the token belongs to. Find it under "
                            "**Settings > Business Profile**, or in the sub-account URL after `/location/`."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
