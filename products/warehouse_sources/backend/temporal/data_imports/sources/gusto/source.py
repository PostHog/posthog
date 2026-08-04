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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gusto import GustoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto import (
    GUSTO_API_VERSION,
    GustoResumeConfig,
    gusto_source,
    validate_credentials as validate_gusto_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.settings import (
    ENDPOINTS,
    GUSTO_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GustoSource(ResumableSource[GustoSourceConfig, GustoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = (GUSTO_API_VERSION,)
    default_version = GUSTO_API_VERSION
    api_docs_url = "https://docs.gusto.com/embedded-payroll/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUSTO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GUSTO,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Gusto",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["payroll", "hris", "zenpayroll"],
            caption="""Pull your Gusto payroll and people data into the PostHog Data warehouse.

Company data is only readable through an authorization-code OAuth grant, so you bring your own Gusto developer app: register it in the [Gusto Developer Portal](https://dev.gusto.com), authorize it against your company as a payroll admin, then enter the app's client ID and secret along with the resulting refresh token.

Gusto rotates refresh tokens, so the token you paste here is exchanged on every sync. If syncs start failing with an authorization error, generate a fresh refresh token and update this connection.""",
            iconPath="/static/services/gusto.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gusto",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Demo", value="demo"),
                        ],
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
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Both the production and demo hosts start `https://api.gusto`, so match on that prefix.
        return {
            "400 Client Error: Bad Request for url: https://api.gusto": "Gusto rejected these OAuth credentials. Refresh tokens rotate on use — generate a new one and reconnect.",
            "401 Client Error: Unauthorized for url: https://api.gusto": "Gusto authentication failed. Check your client ID and secret, then reconnect with a fresh refresh token.",
            "403 Client Error: Forbidden for url: https://api.gusto": "Your Gusto app is not authorized to read this data. Reconnect with a payroll admin authorization for the company.",
        }

    def get_schemas(
        self,
        config: GustoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the money-movement endpoints take a server-side date filter; the people and
        # configuration tables have no updated-since parameter, so they stay full refresh. Those
        # three are merge-only: a payroll is restated as it moves from calculated to processed, so
        # appending would leave duplicate rows behind.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=tuple(INCREMENTAL_FIELDS))

    def validate_credentials(
        self,
        config: GustoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # One OAuth grant covers every company-scoped endpoint, so a single probe validates them all.
        return validate_gusto_credentials(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GustoResumeConfig]:
        return ResumableSourceManager[GustoResumeConfig](inputs, GustoResumeConfig)

    def source_for_pipeline(
        self,
        config: GustoSourceConfig,
        resumable_source_manager: ResumableSourceManager[GustoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in GUSTO_ENDPOINTS:
            raise ValueError(f"Unknown Gusto schema '{inputs.schema_name}'")

        return gusto_source(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
