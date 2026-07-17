from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TailscaleSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import (
    AUDIT_LOG_RETENTION_DAYS,
    AUDIT_LOGS_ENDPOINT,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.tailscale import (
    OAUTH_CREDENTIALS_ERROR,
    TailscaleResumeConfig,
    tailscale_source,
    validate_credentials as validate_tailscale_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TailscaleSource(ResumableSource[TailscaleSourceConfig, TailscaleResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TAILSCALE

    @property
    def connection_host_fields(self) -> list[str]:
        # `tailnet` selects which tailnet the stored credential reads from; retargeting it
        # must re-require the secret so a preserved multi-tailnet credential can't be aimed
        # at another tailnet by an editor who doesn't hold the credential.
        return ["tailnet"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TAILSCALE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Tailscale",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["vpn", "wireguard", "tailnet"],
            caption="""Sync your Tailscale devices, users, keys, and configuration audit logs into the PostHog Data warehouse.

An **OAuth client** is the recommended credential for recurring syncs — API access tokens expire after at most 90 days. Create one in the [Tailscale admin console](https://login.tailscale.com/admin/settings/oauth) under **Settings > OAuth clients**, with read scopes for the tables you want to sync (for example `devices:core:read`, `users:read`, `auth_keys:read`, and `logs:configuration:read`).

Alternatively, generate an API access token under **Settings > Keys**. Leave the tailnet field blank to use the credential's default tailnet.""",
            iconPath="/static/services/tailscale.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tailscale",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="oauth_client",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="OAuth client",
                                value="oauth_client",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="client_id",
                                            label="OAuth client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="client_secret",
                                            label="OAuth client secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="tskey-client-...",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="API access token",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="tskey-api-...",
                                            caption="API access tokens expire after at most 90 days — prefer an OAuth client for long-running syncs.",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="tailnet",
                        label="Tailnet",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="-",
                        caption="Your tailnet name, e.g. `example.com`. Leave blank to use the credential's default tailnet.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Tailscale credentials. API access tokens expire after at most 90 days — generate a new token (or switch to an OAuth client) and reconnect.",
            "403 Client Error": "Your Tailscale credentials lack the required scopes. Grant the read scopes for the tables you sync (e.g. `devices:core:read`, `logs:configuration:read`) and reconnect.",
            "404 Client Error": "Tailnet not found. Check the tailnet name on the source, or leave it blank to use the credential's default tailnet.",
            OAUTH_CREDENTIALS_ERROR: "Invalid Tailscale OAuth client credentials. Please check the client ID and secret and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TailscaleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Audit log records carry no unique id, so incremental (merge) syncs are
                # impossible — the server-side time filter powers append syncs instead.
                supports_incremental=False,
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=f"Only syncs the last {AUDIT_LOG_RETENTION_DAYS} days (Tailscale's audit log retention)"
                if endpoint == AUDIT_LOGS_ENDPOINT
                else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: TailscaleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_tailscale_credentials(
            api_key=config.auth_method.api_key,
            client_id=config.auth_method.client_id,
            client_secret=config.auth_method.client_secret,
            tailnet=config.tailnet,
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TailscaleResumeConfig]:
        return ResumableSourceManager[TailscaleResumeConfig](inputs, TailscaleResumeConfig)

    def source_for_pipeline(
        self,
        config: TailscaleSourceConfig,
        resumable_source_manager: ResumableSourceManager[TailscaleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return tailscale_source(
            api_key=config.auth_method.api_key,
            client_id=config.auth_method.client_id,
            client_secret=config.auth_method.client_secret,
            tailnet=config.tailnet,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
