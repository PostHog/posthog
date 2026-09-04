from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk import (
    ClerkResumeConfig,
    clerk_source,
    validate_credentials as validate_clerk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import ENDPOINTS, RETIRED_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClerkSource(ResumableSource[ClerkSourceConfig, ClerkResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://clerk.com/docs/reference/backend-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLERK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLERK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Clerk",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Clerk secret key to automatically pull your Clerk data into the PostHog Data warehouse.

You can find your secret key in your [Clerk Dashboard](https://dashboard.clerk.com/) under **API Keys**.

The secret key starts with `sk_live_`.
""",
            iconPath="/static/services/clerk.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClerkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Clerk only supports full refresh - the API doesn't support filtering by updated_at
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clerk.com": "Your Clerk secret key is invalid or has been revoked. Please update the secret key in your Clerk dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.clerk.com": "Your Clerk secret key does not have permission to access this endpoint. Please check the key's permissions in your Clerk dashboard.",
            # Clerk answers 410 for endpoints it has removed. Schema discovery retires the table
            # within a few hours, so this only covers runs that start in between.
            "410 Client Error: Gone for url: https://api.clerk.com": "Clerk removed this endpoint from its API, so this table can't sync any more. Turn off syncing for this table.",
            # Clerk's own API spec documents only 402/403/422 as possible error responses for this
            # (deprecated) list endpoint — no successful, well-formed request should ever hit this,
            # so a 422 here means SAML connections (Enterprise SSO) aren't available on this Clerk
            # instance. Scoped to this path, not all of api.clerk.com, since 422 elsewhere can mean
            # a genuinely bad request that's worth investigating rather than an account limitation.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/saml_connections": "SAML connections (Enterprise SSO) aren't available on your Clerk plan or instance. Turn off syncing for this table, or enable SAML connections in your Clerk dashboard.",
            # Clerk answers 422 feature_requires_email_address_enabled for enterprise_connections when
            # Enterprise SSO isn't available on the instance. The unfiltered list request is identical
            # every run, so it re-fails on every schedule; classify it so the schema pauses instead of
            # retrying. Scoped to this path, mirroring saml_connections, since a 422 elsewhere can be a
            # genuinely bad request worth investigating rather than an account limitation.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/enterprise_connections": "Enterprise SSO connections aren't available on your Clerk plan or instance. Turn off syncing for this table, or enable Enterprise SSO in your Clerk dashboard.",
            # Clerk's list api_keys endpoint requires a subject (a user or organization id), so the
            # unfiltered list request we send is rejected with a 400 every run. Scoped to this path,
            # not all of api.clerk.com, since a 400 elsewhere can be a genuinely bad request worth
            # investigating rather than an endpoint that can't be listed.
            "400 Client Error: Bad Request for url: https://api.clerk.com/v1/api_keys": "The API keys table can't be synced from Clerk. Turn off syncing for this table.",
            # Clerk answers 404 resource_not_found for redirect_urls on instances/plans where the
            # resource isn't available. The request is identical every run, so it re-fails on every
            # schedule; classify it so the schema is paused instead of burning a job each time. Scoped
            # to this path, not all of api.clerk.com, since a 404 elsewhere can be a genuinely missing
            # record worth investigating rather than an account limitation.
            "404 Client Error: Not Found for url: https://api.clerk.com/v1/redirect_urls": "The redirect URLs table isn't available on your Clerk plan or instance. Turn off syncing for this table.",
            **{reason: reason for reason in RETIRED_ENDPOINTS.values()},
        }

    def validate_credentials(
        self, config: ClerkSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_clerk_credentials(config.secret_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClerkResumeConfig]:
        return ResumableSourceManager[ClerkResumeConfig](inputs, ClerkResumeConfig)

    def source_for_pipeline(
        self,
        config: ClerkSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClerkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clerk_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
        )
