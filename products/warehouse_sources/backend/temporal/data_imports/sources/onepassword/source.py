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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OnePasswordSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword import (
    ONEPASSWORD_REGION_HOSTS,
    OnePasswordResumeConfig,
    introspect,
    onepassword_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ONEPASSWORD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OnePasswordSource(ResumableSource[OnePasswordSourceConfig, OnePasswordResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONEPASSWORD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONE_PASSWORD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="1Password",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull your 1Password security event streams — sign-in attempts, item usages, and audit events — into the PostHog Data warehouse.

This uses the 1Password Events API, which requires a 1Password Business or Enterprise plan. [Create an Events Reporting integration](https://support.1password.com/events-reporting/) in your 1Password admin console and issue a bearer token with the event types you want to sync:
- Sign-in attempts
- Item usages
- Audit events

Select the region where your 1Password account is hosted — the Events API is served from a region-specific address.""",
            iconPath="/static/services/onepassword.png",
            docsUrl="https://posthog.com/docs/cdp/sources/onepassword",
            keywords=["agilebits", "events api", "audit log", "security events", "siem"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Account region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="1Password.com (events.1password.com)", value="us"),
                            SourceFieldSelectConfigOption(label="1Password.ca (events.1password.ca)", value="ca"),
                            SourceFieldSelectConfigOption(label="1Password.eu (events.1password.eu)", value="eu"),
                            SourceFieldSelectConfigOption(
                                label="1Password Enterprise (events.ent.1password.com)", value="enterprise"
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Events Reporting token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="eyJhbGciOiJFUzI1NiIsIm...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 1Password returns 401 both for an invalid/revoked token and for a token missing the
        # endpoint's feature scope, so one message covers both. One entry per regional host.
        message = (
            "Your 1Password Events Reporting token is invalid, revoked, or missing the feature scope for this "
            "table. Issue a new bearer token with the required event types in your 1Password admin console, "
            "then reconnect."
        )
        return {
            f"401 Client Error: Unauthorized for url: {host}": message for host in ONEPASSWORD_REGION_HOSTS.values()
        }

    def get_schemas(
        self,
        config: OnePasswordSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ONEPASSWORD_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # `start_time` is a genuine server-side timestamp filter on every stream.
                supports_incremental=True,
                # Events are immutable, but incremental runs re-pull a boundary window that only
                # merge dedupes on `uuid` — append would materialize the overlap as duplicates.
                supports_append=False,
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
        config: OnePasswordSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        introspection = introspect(config.region, config.api_token)
        if introspection is None:
            return False, "Invalid 1Password Events Reporting token. Check the token and the selected account region."

        if schema_name is not None and schema_name in ONEPASSWORD_ENDPOINTS:
            feature = ONEPASSWORD_ENDPOINTS[schema_name].feature
            if feature not in (introspection.get("features") or []):
                return (
                    False,
                    f"Your Events Reporting token doesn't include the `{feature}` event type. Issue a token with "
                    "that event type in your 1Password admin console.",
                )

        return True, None

    def get_endpoint_permissions(
        self, config: OnePasswordSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        introspection = introspect(config.region, config.api_token)
        if introspection is None:
            # Never block the schema picker on a failed probe; sync-time errors surface separately.
            return dict.fromkeys(endpoints)

        features = introspection.get("features") or []
        result: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = ONEPASSWORD_ENDPOINTS.get(endpoint)
            if endpoint_config is None or endpoint_config.feature in features:
                result[endpoint] = None
            else:
                result[endpoint] = (
                    f"Your Events Reporting token doesn't include the `{endpoint_config.feature}` event type"
                )
        return result

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OnePasswordResumeConfig]:
        return ResumableSourceManager[OnePasswordResumeConfig](inputs, OnePasswordResumeConfig)

    def source_for_pipeline(
        self,
        config: OnePasswordSourceConfig,
        resumable_source_manager: ResumableSourceManager[OnePasswordResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return onepassword_source(
            region=config.region,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
