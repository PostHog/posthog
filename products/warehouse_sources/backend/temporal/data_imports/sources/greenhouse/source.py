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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GreenhouseSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.greenhouse import (
    GreenhouseResumeConfig,
    greenhouse_source,
    validate_credentials as validate_greenhouse_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    ENDPOINTS,
    GREENHOUSE_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GreenhouseSource(ResumableSource[GreenhouseSourceConfig, GreenhouseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GREENHOUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GREENHOUSE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Greenhouse",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Greenhouse Harvest API key to automatically pull your Greenhouse recruiting data into the PostHog Data warehouse.

You can create a Harvest API key in Greenhouse under **Configure → Dev Center → API Credential Management**.

Grant the key read (`GET`) access to the resources you want to sync — for example **Candidates**, **Applications**, **Jobs**, **Job Posts**, **Offers**, **Scorecards**, **Scheduled Interviews**, and **Users**.""",
            iconPath="/static/services/greenhouse.png",
            docsUrl="https://posthog.com/docs/cdp/sources/greenhouse",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GreenhouseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GreenhouseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # At source-create (`schema_name is None`) accept a 403 — the key may legitimately be
        # scoped only to the endpoints the user wants. For a per-schema check, probe that
        # endpoint and surface a missing-scope error.
        if schema_name is not None and schema_name in GREENHOUSE_ENDPOINTS:
            return validate_greenhouse_credentials(
                config.api_key, path=GREENHOUSE_ENDPOINTS[schema_name].path, accept_forbidden=False
            )

        return validate_greenhouse_credentials(config.api_key, accept_forbidden=True)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://harvest.greenhouse.io": "Your Greenhouse API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://harvest.greenhouse.io": "Your Greenhouse API key does not have the required permissions. Please grant read access to this resource and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GreenhouseResumeConfig]:
        return ResumableSourceManager[GreenhouseResumeConfig](inputs, GreenhouseResumeConfig)

    def source_for_pipeline(
        self,
        config: GreenhouseSourceConfig,
        resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return greenhouse_source(
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
