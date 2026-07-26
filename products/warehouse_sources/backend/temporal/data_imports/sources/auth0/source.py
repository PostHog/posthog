from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.auth0 import (
    HOST_NOT_ALLOWED_ERROR,
    PAGINATION_STALLED_ERROR,
    Auth0ResumeConfig,
    auth0_source,
    validate_credentials as validate_auth0_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.auth0 import Auth0SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Auth0Source(ResumableSource[Auth0SourceConfig, Auth0ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://auth0.com/docs/api/management/v2"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUTH0

    @property
    def connection_host_fields(self) -> list[str]:
        # `auth0_domain` is where the stored client secret is sent; retargeting it must re-require it.
        return ["auth0_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AUTH0,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Auth0",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["okta", "identity", "sso", "authentication", "ciam"],
            caption="""Enter your Auth0 tenant domain and a machine-to-machine application's credentials to pull your users, tenant logs, and tenant configuration into the PostHog Data warehouse.

In the Auth0 dashboard go to **Applications > Applications**, create a **Machine to Machine** application, and authorize it for the **Auth0 Management API**. Grant the read scopes for the tables you want to sync: `read:users`, `read:logs`, `read:clients`, `read:connections`, `read:roles`, `read:organizations`, `read:resource_servers`, `read:actions`, `read:log_streams`.

Use your canonical tenant domain (for example `your-tenant.us.auth0.com`), not a custom domain. Auth0 only issues Management API tokens for the canonical one.""",
            iconPath="/static/services/auth0.png",
            docsUrl="https://posthog.com/docs/cdp/sources/auth0",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth0_domain",
                        label="Auth0 domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-tenant.us.auth0.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Auth0 rejected the credentials. Check the machine-to-machine application's client ID and secret, then reconnect.",
            "403 Client Error": "Your Auth0 application is missing a read scope for this table. Grant it on the Management API and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Auth0 domain is not allowed. Use your tenant's canonical Auth0 domain.",
            PAGINATION_STALLED_ERROR: "Auth0 could not page past its 1000-result limit because too many rows share the same timestamp.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Auth0SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Users are mutable and the window's inclusive lower bound re-reads its boundary rows, so
        # merge is the only safe incremental mode — append would duplicate rows.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: Auth0SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_auth0_credentials(
            domain=config.auth0_domain,
            client_id=config.client_id,
            client_secret=config.client_secret,
            api_version=self.resolve_api_version(api_version),
            schema_name=schema_name,
            team_id=team_id,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Auth0ResumeConfig]:
        return ResumableSourceManager[Auth0ResumeConfig](inputs, Auth0ResumeConfig)

    def source_for_pipeline(
        self,
        config: Auth0SourceConfig,
        resumable_source_manager: ResumableSourceManager[Auth0ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return auth0_source(
            domain=config.auth0_domain,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
