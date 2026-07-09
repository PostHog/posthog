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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UbidotsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.settings import (
    DEFAULT_UBIDOTS_API_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    UBIDOTS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.ubidots import (
    UbidotsResumeConfig,
    ubidots_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UbidotsSource(ResumableSource[UbidotsSourceConfig, UbidotsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UBIDOTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UBIDOTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Ubidots",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["iot", "sensors", "telemetry"],
            caption="""Enter your Ubidots API token to pull your IoT devices, variables, and sensor values into the PostHog Data warehouse.

Use the permanent token from **your profile → API Credentials** in Ubidots — tokens minted via the temporary-token endpoint expire after a few hours and will break syncs. Industrial and enterprise accounts use the default API base URL; pick `https://things.ubidots.com` only for legacy STEM accounts.
""",
            iconPath="/static/services/ubidots.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ubidots",
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
                        name="api_base_url",
                        label="API base URL",
                        required=False,
                        defaultValue=DEFAULT_UBIDOTS_API_BASE_URL,
                        options=[
                            SourceFieldSelectConfigOption(
                                label=DEFAULT_UBIDOTS_API_BASE_URL, value=DEFAULT_UBIDOTS_API_BASE_URL
                            ),
                            SourceFieldSelectConfigOption(
                                label="https://things.ubidots.com", value="https://things.ubidots.com"
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ubidots.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message_401 = (
            "Your Ubidots API token is invalid or has expired. Use the permanent token from your profile's "
            "API Credentials page, then reconnect."
        )
        message_403 = (
            "Your Ubidots API token does not have access to this data. Check the token owner's permissions, "
            "then reconnect."
        )
        return {
            "401 Client Error: Unauthorized for url: https://industrial.api.ubidots.com": message_401,
            "403 Client Error: Forbidden for url: https://industrial.api.ubidots.com": message_403,
            "401 Client Error: Unauthorized for url: https://things.ubidots.com": message_401,
            "403 Client Error: Forbidden for url: https://things.ubidots.com": message_403,
        }

    def get_schemas(
        self,
        config: UbidotsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only `values` filters server-side (`start`/`end` millisecond timestamps); the v2.0
        # metadata endpoints expose no monotonic update cursor, so they are full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=UBIDOTS_ENDPOINTS[endpoint].supports_incremental,
                supports_append=UBIDOTS_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: UbidotsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Ubidots tokens are account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_token, config.api_base_url)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UbidotsResumeConfig]:
        return ResumableSourceManager[UbidotsResumeConfig](inputs, UbidotsResumeConfig)

    def source_for_pipeline(
        self,
        config: UbidotsSourceConfig,
        resumable_source_manager: ResumableSourceManager[UbidotsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in UBIDOTS_ENDPOINTS:
            raise ValueError(f"Unknown Ubidots schema '{inputs.schema_name}'")

        return ubidots_source(
            api_token=config.api_token,
            api_base_url=config.api_base_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
