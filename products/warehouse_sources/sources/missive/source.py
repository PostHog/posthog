from typing import Optional, cast

from products.warehouse_sources.sources.missive._config import MissiveSourceConfig
from products.warehouse_sources.sources.missive.missive import (
    MissiveResumeConfig,
    missive_source,
    validate_credentials as validate_missive_credentials,
)
from products.warehouse_sources.sources.missive.settings import ENDPOINTS, INCREMENTAL_FIELDS, MERGE_ONLY_ENDPOINTS
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
class MissiveSource(ResumableSource[MissiveSourceConfig, MissiveResumeConfig]):
    # Missive publishes no SDK package. Its iframe integrations load missive.js from this host.
    codebase_detection = detect(env=("^MISSIVE_",), script_hosts=("integrations.missiveapp.com",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The API has only ever had `/v1`, so it is unversioned.
    api_docs_url = "https://missiveapp.com/docs/developers/rest-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MISSIVE

    @property
    def credential_auth_type(self) -> str:
        # The scaffold had no fields, so `facade/credential_auth_types.py` froze "credentials" for this kind.
        return "credentials"

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.missive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,  # noqa: PLC0415
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://public.missiveapp.com": "Missive rejected your API token. Create a new token in Missive under Preferences > API, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://public.missiveapp.com": "Missive refused your API token. Check that your organization is on the Missive Productive plan, which includes API access, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: MissiveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY_ENDPOINTS)

    def validate_credentials(
        self,
        config: MissiveSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_missive_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MissiveResumeConfig]:
        return ResumableSourceManager[MissiveResumeConfig](inputs, MissiveResumeConfig)

    def source_for_pipeline(
        self,
        config: MissiveSourceConfig,
        resumable_source_manager: ResumableSourceManager[MissiveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return missive_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MISSIVE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Missive",
            caption="""Enter a Missive API token to sync your shared inbox data.

Create the token in Missive under **Preferences > API**. Only organizations on the Missive Productive plan can create tokens.

Missive tokens are personal, so PostHog syncs the conversations, contacts and other data that the token's owner can see.""",
            releaseStatus=ReleaseStatus.BETA,
            docsUrl="https://posthog.com/docs/cdp/sources/missive",
            iconPath="/static/warehouse-sources/missive/icon.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="missive_pat-...",
                        secret=True,
                    ),
                ],
            ),
        )
