from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ProductKey,
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
from products.warehouse_sources.sources.userback._config import UserbackSourceConfig
from products.warehouse_sources.sources.userback.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.userback.userback import (
    USERBACK_API_VERSION,
    UserbackResumeConfig,
    userback_source,
    validate_credentials as validate_userback_credentials,
)


@SourceRegistry.register
class UserbackSource(ResumableSource[UserbackSourceConfig, UserbackResumeConfig]):
    codebase_detection = detect(
        env=("^USERBACK_", "^NEXT_PUBLIC_USERBACK_", "^VITE_USERBACK_", "^REACT_APP_USERBACK_"),
        script_hosts=("static.userback.io",),
        npm=("@userback/widget", "@userback/react", "@userback/vue"),
        alternative_to=(ProductKey.SURVEYS, ProductKey.SESSION_REPLAY),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = (USERBACK_API_VERSION,)
    default_version = USERBACK_API_VERSION
    api_docs_url = "https://docs.userback.io/reference/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USERBACK

    @property
    def credential_auth_type(self) -> str:
        # The scaffold had no fields, so `facade/credential_auth_types.py` froze "credentials" for this kind.
        # The frozen value is stored data, so keep it rather than the "token" a single secret field derives.
        return "credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USERBACK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Userback",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter a Userback API token to sync your feedback, feedback comments, session recordings, projects, members, and workflows.

Create a token in Userback under [Workspace settings > API tokens](https://app.userback.io/account/api_token). Userback requires a Premium plan and an admin account for REST API access.""",
            iconPath="/static/services/userback.png",
            docsUrl="https://posthog.com/docs/cdp/sources/userback",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.userback.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://rest.userback.io": "Userback rejected your API token. Create a new token in Userback under Workspace settings > API tokens, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://rest.userback.io": "Userback refused API access for this token. The REST API needs a Premium plan and an admin account. Check your plan, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: UserbackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: UserbackSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_userback_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UserbackResumeConfig]:
        return ResumableSourceManager[UserbackResumeConfig](inputs, UserbackResumeConfig)

    def source_for_pipeline(
        self,
        config: UserbackSourceConfig,
        resumable_source_manager: ResumableSourceManager[UserbackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return userback_source(
            api_token=config.api_token,
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
