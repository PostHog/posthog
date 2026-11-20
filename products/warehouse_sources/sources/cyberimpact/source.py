from typing import Optional, cast

from products.warehouse_sources.sources.cyberimpact._config import CyberimpactSourceConfig
from products.warehouse_sources.sources.cyberimpact.cyberimpact import (
    INVALID_TOKEN_ERROR,
    CyberimpactResumeConfig,
    cyberimpact_source,
    validate_credentials as validate_cyberimpact_credentials,
)
from products.warehouse_sources.sources.cyberimpact.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "Cyberimpact"


@SourceRegistry.register
class CyberimpactSource(ResumableSource[CyberimpactSourceConfig, CyberimpactResumeConfig]):
    codebase_detection = detect(env=("^CYBERIMPACT_",))

    lists_tables_without_credentials = True  # Static endpoint catalog, safe for public docs.
    # The API has no version in its paths or headers.
    api_docs_url = "https://api.cyberimpact.com/docs"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_auth_type(self) -> str:
        # Frozen as "credentials" when the source shipped as a stub with no fields.
        return "credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_TOKEN_ERROR,
            "403 Client Error": INVALID_TOKEN_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.cyberimpact.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CyberimpactSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Append would add a new row for every member edit, so members only merge.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS.keys())

    def validate_credentials(
        self,
        config: CyberimpactSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cyberimpact_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CyberimpactResumeConfig]:
        return ResumableSourceManager[CyberimpactResumeConfig](inputs, CyberimpactResumeConfig)

    def source_for_pipeline(
        self,
        config: CyberimpactSourceConfig,
        resumable_source_manager: ResumableSourceManager[CyberimpactResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cyberimpact_source(
            api_token=config.api_token,
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
            name=self.source_type,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Cyberimpact",
            caption=(
                "Connect your Cyberimpact account with an API token to sync members, groups, unsubscribes, "
                "bounces, mailings and their statistics, opens, clicks, and templates. An account "
                "administrator creates the token in Cyberimpact under **Settings > API tokens**."
            ),
            iconPath="/static/warehouse-sources/cyberimpact/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cyberimpact",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
        )
