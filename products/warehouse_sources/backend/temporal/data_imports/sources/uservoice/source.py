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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UservoiceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    USERVOICE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.uservoice import (
    UservoiceResumeConfig,
    uservoice_source,
    validate_credentials as validate_uservoice_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UservoiceSource(ResumableSource[UservoiceSourceConfig, UservoiceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USERVOICE

    @property
    def connection_host_fields(self) -> list[str]:
        # The token is sent to `<subdomain>.uservoice.com`, so changing the subdomain must re-require it.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.USERVOICE,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="UserVoice",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your UserVoice account subdomain and API access token to pull your UserVoice data into the PostHog Data warehouse.

Create a trusted API client under **Settings → Channels → Add API Client** in your UserVoice Admin Console, then generate an access token to use here. The token has admin-level read access to your account's feedback data.""",
            iconPath="/static/services/uservoice.png",
            docsUrl="https://posthog.com/docs/cdp/sources/uservoice",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uservoice.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. The base host
            # is per-account, so match the stable status text rather than a fixed URL.
            "401 Client Error: Unauthorized": "Your UserVoice API token is invalid or has been revoked. Generate a new token in your UserVoice Admin Console, then reconnect.",
            "403 Client Error: Forbidden": "Your UserVoice API token is missing the permissions needed to sync this data. Check the API client's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: UservoiceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = USERVOICE_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: UservoiceSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_uservoice_credentials(config.subdomain, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid UserVoice API token"
        return False, "Could not connect to UserVoice with the provided subdomain and API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UservoiceResumeConfig]:
        return ResumableSourceManager[UservoiceResumeConfig](inputs, UservoiceResumeConfig)

    def source_for_pipeline(
        self,
        config: UservoiceSourceConfig,
        resumable_source_manager: ResumableSourceManager[UservoiceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return uservoice_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
