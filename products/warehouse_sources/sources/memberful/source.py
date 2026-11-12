from typing import Optional, cast

from products.warehouse_sources.sources.memberful._config import MemberfulSourceConfig
from products.warehouse_sources.sources.memberful.memberful import (
    MemberfulResumeConfig,
    memberful_source,
    validate_credentials as validate_memberful_credentials,
)
from products.warehouse_sources.sources.memberful.settings import ENDPOINTS, INCREMENTAL_FIELDS, MEMBERFUL_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    NOT_DETECTABLE,
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
)


@SourceRegistry.register
class MemberfulSource(ResumableSource[MemberfulSourceConfig, MemberfulResumeConfig]):
    # Memberful ships no official SDK package or documented environment key to detect.
    codebase_detection = NOT_DETECTABLE

    # The GraphQL API has one unversioned endpoint, so only the docs URL is declared.
    api_docs_url = "https://memberful.com/docs/api-reference/memberful-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEMBERFUL

    @property
    def connection_host_fields(self) -> list[str]:
        # `subdomain` names the account the stored API key is sent to; changing it must re-require the key.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEMBERFUL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Memberful",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Memberful account subdomain and API key to pull your members, subscriptions and orders into the PostHog Data warehouse.

To create an API key, go to **Settings → Custom applications** in your Memberful dashboard, add a custom application with API key access, then copy its API key.

Your subdomain is the part before `.memberful.com` in your Memberful dashboard URL.""",
            iconPath="/static/services/memberful.png",
            docsUrl="https://posthog.com/docs/cdp/sources/memberful",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-account",
                        secret=False,
                    ),
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
        from products.warehouse_sources.sources.memberful.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Memberful API key is invalid or was deleted. Create a new API key under Settings → Custom applications in Memberful, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Memberful API key has no access to the API. Check the custom application settings in Memberful, then reconnect.",
            "Invalid authentication token": "Your Memberful API key is invalid or was deleted. Create a new API key under Settings → Custom applications in Memberful, then reconnect.",
            "Memberful account not found": "No Memberful account uses this subdomain. Check the account subdomain, then reconnect.",
            "Invalid Memberful account subdomain": "The Memberful account subdomain is not valid. Use the part before .memberful.com, then reconnect.",
        }

    def get_retryable_errors(self) -> set[str]:
        # Rate limits, 5xx answers and network failures are retried with backoff first. When those
        # retries run out, the failure is still transient, so Temporal retries the activity.
        return {"Memberful API error (retryable)"}

    def get_schemas(
        self,
        config: MemberfulSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS[endpoint]),
                supports_append=MEMBERFUL_ENDPOINTS[endpoint].supports_append,
                prefers_full_refresh=MEMBERFUL_ENDPOINTS[endpoint].prefers_full_refresh,
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: MemberfulSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_memberful_credentials(config.subdomain, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MemberfulResumeConfig]:
        return ResumableSourceManager[MemberfulResumeConfig](inputs, MemberfulResumeConfig)

    def source_for_pipeline(
        self,
        config: MemberfulSourceConfig,
        resumable_source_manager: ResumableSourceManager[MemberfulResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return memberful_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
