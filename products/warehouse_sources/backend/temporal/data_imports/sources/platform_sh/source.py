from typing import Optional, cast

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlatformShSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.platform_sh import (
    AUTH_FAILED_MESSAGE,
    PlatformShResumeConfig,
    platform_sh_source,
    validate_credentials as validate_platform_sh_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLATFORM_SH_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


@SourceRegistry.register
class PlatformShSource(ResumableSource[PlatformShSourceConfig, PlatformShResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api.platform.sh/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLATFORMSH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLATFORM_SH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Platform.sh",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Platform.sh (or Upsun) API token to sync your organizations, projects, environments, and deploy activity into the PostHog Data warehouse.

Create an API token in the Console under **My profile > API tokens** ([Platform.sh](https://docs.platform.sh/administration/cli/api-tokens.html) / [Upsun](https://docs.upsun.com/administration/cli/api-tokens.html)). The token has the same access as your user account, so no extra scopes are needed. Pick the API endpoint matching the product you use — a Platform.sh token does not work against the Upsun API, and vice versa.
""",
            iconPath="/static/services/platform_sh.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/platform-sh",
            keywords=["paas", "upsun", "deployments", "hosting", "devops"],
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
                    SourceFieldSelectConfig(
                        name="platform",
                        label="API endpoint",
                        required=True,
                        defaultValue="platform_sh",
                        options=[
                            SourceFieldSelectConfigOption(label="Platform.sh (api.platform.sh)", value="platform_sh"),
                            SourceFieldSelectConfigOption(label="Upsun (api.upsun.com)", value="upsun"),
                        ],
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # `platform` selects which vendor host the stored API token is sent to; switching brands
        # must re-require the token (a Platform.sh token is invalid on Upsun anyway).
        return ["platform"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.platform_sh.canonical_descriptions import (  # noqa: PLC0415 — lazy sibling import, matching every other source
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        invalid_token_message = (
            "Your Platform.sh API token is invalid or has been revoked. "
            "Create a new API token in the Console and reconnect."
        )
        forbidden_message = (
            "Your Platform.sh API token does not have access to this resource. "
            "Use a token for a user with access to the organizations you want to sync."
        )
        return {
            # Raised by the token exchange when the auth server rejects the API token.
            AUTH_FAILED_MESSAGE: invalid_token_message,
            # A 401 that survives one token re-exchange, on either brand host.
            "401 Client Error: Unauthorized for url: https://api.platform.sh": invalid_token_message,
            "401 Client Error: Unauthorized for url: https://api.upsun.com": invalid_token_message,
            "403 Client Error: Forbidden for url: https://api.platform.sh": forbidden_message,
            "403 Client Error: Forbidden for url: https://api.upsun.com": forbidden_message,
        }

    def get_schemas(
        self,
        config: PlatformShSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = []
        for endpoint in ENDPOINTS:
            endpoint_config = PLATFORM_SH_ENDPOINTS[endpoint]
            supports_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                    should_sync_default=endpoint_config.should_sync_default,
                    default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
                )
            )
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: PlatformShSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_platform_sh_credentials(config.api_token, config.platform, logger)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlatformShResumeConfig]:
        return ResumableSourceManager[PlatformShResumeConfig](inputs, PlatformShResumeConfig)

    def source_for_pipeline(
        self,
        config: PlatformShSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlatformShResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return platform_sh_source(
            api_token=config.api_token,
            platform=config.platform,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
