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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.fillout import (
    fillout_source,
    validate_credentials as validate_fillout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.settings import (
    ALLOWED_FILLOUT_API_BASE_URLS,
    DEFAULT_FILLOUT_API_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FilloutSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FilloutSource(SimpleSource[FilloutSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FILLOUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FILLOUT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Fillout",
            iconPath="/static/services/fillout.png",
            caption="""Enter a Fillout API key to sync forms and submissions.

Supported endpoints:
- `forms`
- `submissions`

You can generate an API key in your Fillout account under **Settings → Developer**.
""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="fo_...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="api_base_url",
                        label="API base URL",
                        required=False,
                        defaultValue=DEFAULT_FILLOUT_API_BASE_URL,
                        options=[
                            SourceFieldSelectConfigOption(
                                label=DEFAULT_FILLOUT_API_BASE_URL, value=DEFAULT_FILLOUT_API_BASE_URL
                            ),
                            SourceFieldSelectConfigOption(
                                label="https://eu-api.fillout.com/v1/api",
                                value="https://eu-api.fillout.com/v1/api",
                            ),
                        ],
                    ),
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Fillout API key. Please update your key and reconnect.",
            "403 Client Error": "Fillout API key is missing the required permissions. Please update the key and reconnect.",
        }

    def get_schemas(
        self,
        config: FilloutSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []
        for endpoint in ENDPOINTS:
            if names and endpoint not in names:
                continue

            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            supports_incremental = bool(incremental_fields)
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=incremental_fields,
                )
            )
        return schemas

    def validate_credentials(
        self, config: FilloutSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        api_base_url = config.api_base_url or DEFAULT_FILLOUT_API_BASE_URL
        if api_base_url not in ALLOWED_FILLOUT_API_BASE_URLS:
            return (
                False,
                "API base URL must be one of https://api.fillout.com/v1/api or https://eu-api.fillout.com/v1/api.",
            )

        return validate_fillout_credentials(
            api_key=config.api_key,
            api_base_url=api_base_url,
            schema_name=schema_name,
        )

    def source_for_pipeline(self, config: FilloutSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return fillout_source(
            api_key=config.api_key,
            api_base_url=config.api_base_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fillout.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS
