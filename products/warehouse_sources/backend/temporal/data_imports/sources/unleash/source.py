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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UnleashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.settings import (
    ENDPOINTS,
    UNLEASH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.unleash import (
    UnleashResumeConfig,
    check_endpoint_permissions,
    unleash_source,
    validate_credentials as validate_unleash_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UnleashSource(ResumableSource[UnleashSourceConfig, UnleashResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UNLEASH

    @property
    def connection_host_fields(self) -> list[str]:
        # `instance_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["instance_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UNLEASH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Unleash",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["feature flags", "feature toggles", "getunleash"],
            caption="""Enter your Unleash instance URL and an Admin API token to sync your feature flags, projects, environments, strategies, segments, and other configuration data into the PostHog Data warehouse.

The instance URL is where you open the Unleash UI — for Unleash cloud it includes your instance name (e.g. `https://us.app.unleash-hosted.com/your-instance`); for self-hosted it's your server's URL. The token is a [personal access token](https://docs.getunleash.io/how-to/how-to-create-personal-access-tokens) or, on Enterprise, a [service account token](https://docs.getunleash.io/reference/service-accounts); it inherits the owner's permissions, and the `users` table additionally requires the Admin root role. The `features` table uses the flag search API, which requires Unleash 5.12 or newer.
""",
            iconPath="/static/services/unleash.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/unleash",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://us.app.unleash-hosted.com/your-instance",
                        secret=False,
                    ),
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.unleash.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Unleash API token is invalid or has expired. Generate a new personal access token or service account token and reconnect.",
            "Unauthorized for url": "Your Unleash API token is invalid or has expired. Generate a new personal access token or service account token and reconnect.",
            "403 Client Error": "Your Unleash API token does not have permission to read this data. Check the token owner's role (the users table requires the Admin root role), then reconnect.",
        }

    def get_schemas(
        self,
        config: UnleashSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the Admin API exposes no server-side
        # updated_after/created_after filter, so there is no timestamp cursor to advance an
        # incremental sync (see settings.py).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: UnleashSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_unleash_credentials(config.instance_url, config.api_token, schema_name, team_id)

    def get_endpoint_permissions(
        self, config: UnleashSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Tokens inherit their owner's role, so per-table access varies (users needs the Admin
        # root role). Probe each endpoint so the schema picker can flag unreadable tables.
        return check_endpoint_permissions(config.instance_url, config.api_token, endpoints, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UnleashResumeConfig]:
        return ResumableSourceManager[UnleashResumeConfig](inputs, UnleashResumeConfig)

    def source_for_pipeline(
        self,
        config: UnleashSourceConfig,
        resumable_source_manager: ResumableSourceManager[UnleashResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in UNLEASH_ENDPOINTS:
            raise ValueError(f"Unknown Unleash schema '{inputs.schema_name}'")

        return unleash_source(
            instance_url=config.instance_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
