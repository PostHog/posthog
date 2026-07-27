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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightfield import (
    LightfieldSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.lightfield import (
    check_token,
    lightfield_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIGHTFIELD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LightfieldSource(SimpleSource[LightfieldSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2026-03-01",)
    default_version = "2026-03-01"
    api_docs_url = "https://docs.lightfield.app"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIGHTFIELD

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.lightfield.app": "Your Lightfield API key is invalid or has been revoked. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.lightfield.app": "Your Lightfield API key is missing a required scope. Please grant the read scope for the tables you want to sync and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lightfield.canonical_descriptions import (  # noqa: PLC0415 — lazy import keeps the catalog off the registry import path
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LightfieldSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: LightfieldSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        valid, scopes, error = check_token(config.api_key, self.default_version)
        if not valid:
            return False, error

        # At source-create (no schema_name) a live key is enough — users may only grant the
        # scopes for the tables they intend to sync. Per-schema checks enforce the scope.
        if schema_name is not None and scopes is not None:
            endpoint = LIGHTFIELD_ENDPOINTS.get(schema_name)
            if endpoint is not None and endpoint.scope not in scopes:
                return (
                    False,
                    f"Your Lightfield API key is missing the `{endpoint.scope}` scope required to sync {schema_name}.",
                )

        return True, None

    def get_endpoint_permissions(
        self, config: LightfieldSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        try:
            valid, scopes, _ = check_token(config.api_key, self.default_version)
        except Exception:
            valid, scopes = False, None

        # Only a definitive scope list may mark tables unreachable; anything else (throttle,
        # 5xx, network blip) must not block the schema picker.
        if not valid or scopes is None:
            return dict.fromkeys(endpoints)

        granted = set(scopes)
        permissions: dict[str, str | None] = {}
        for name in endpoints:
            endpoint = LIGHTFIELD_ENDPOINTS.get(name)
            if endpoint is None or endpoint.scope in granted:
                permissions[name] = None
            else:
                permissions[name] = f"API key is missing the `{endpoint.scope}` scope"
        return permissions

    def source_for_pipeline(self, config: LightfieldSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return lightfield_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LIGHTFIELD,
            category=DataWarehouseSourceCategory.CRM,
            label="Lightfield",
            caption="""Enter your Lightfield API key to pull your Lightfield CRM data into the PostHog Data warehouse.

You can create an API key in your Lightfield settings (admin access required). Grant the read scope for each table you want to sync:

- `accounts:read` - accounts
- `contacts:read` - contacts
- `opportunities:read` - opportunities
- `meetings:read` - meetings
- `tasks:read` - tasks
- `notes:read` - notes
- `lists:read` - lists
- `members:read` - members
- `emails:read` - emails
""",
            docsUrl="https://posthog.com/docs/cdp/sources/lightfield",
            iconPath="/static/services/lightfield.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_lf_...",
                        secret=True,
                    ),
                ],
            ),
        )
