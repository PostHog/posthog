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
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.formbricks import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    RESPONSE_TOO_LARGE_ERROR,
    RESPONSE_TOO_SLOW_ERROR,
    FormbricksResumeConfig,
    formbricks_source,
    validate_credentials as validate_formbricks_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import (
    ENDPOINTS,
    FORMBRICKS_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FormbricksSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FormbricksSource(ResumableSource[FormbricksSourceConfig, FormbricksResumeConfig]):
    api_docs_url = "https://formbricks.com/docs/api-reference/rest-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FORMBRICKS

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored API key is sent, so retargeting it
        # must re-require the key.
        return ["host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FORMBRICKS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Formbricks",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync surveys, responses, contacts, and more from Formbricks into the PostHog Data warehouse.

Create an API key under **Organization settings → API keys** in Formbricks. API keys are scoped to a single environment, so the connector imports that environment's data.
For self-hosted Formbricks, set your instance URL (for example `https://formbricks.example.com`); leave it empty for Formbricks Cloud.""",
            iconPath="/static/services/formbricks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/formbricks",
            keywords=["surveys", "feedback", "forms"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Formbricks instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://app.formbricks.com",
                        secret=False,
                    ),
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Formbricks API key is invalid or has been revoked. Generate a new key under Organization settings → API keys, then reconnect.",
            "403 Client Error": "Your Formbricks API key does not have access to this data. Check the key's environment permissions, then reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Formbricks host is not allowed. Please use a publicly reachable instance URL.",
            HTTP_NOT_ALLOWED_ERROR: "The Formbricks host must use HTTPS. Please update the instance URL to use https://.",
            RESPONSE_TOO_LARGE_ERROR: "Formbricks returned a response that was too large to process. Please contact support if this persists.",
            RESPONSE_TOO_SLOW_ERROR: "Formbricks took too long to send a response. Check that the instance URL points at a healthy Formbricks server, then reconnect.",
        }

    def get_schemas(
        self,
        config: FormbricksSourceConfig,
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
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FormbricksSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key grants access to its whole environment, so one probe validates every schema.
        return validate_formbricks_credentials(config.host, config.api_key, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FormbricksResumeConfig]:
        return ResumableSourceManager[FormbricksResumeConfig](inputs, FormbricksResumeConfig)

    def source_for_pipeline(
        self,
        config: FormbricksSourceConfig,
        resumable_source_manager: ResumableSourceManager[FormbricksResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in FORMBRICKS_ENDPOINTS:
            raise ValueError(f"Unknown Formbricks schema '{inputs.schema_name}'")

        return formbricks_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
