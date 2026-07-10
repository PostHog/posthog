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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RetentlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.retently import (
    RetentlyResumeConfig,
    retently_source,
    validate_credentials as validate_retently_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RETENTLY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RetentlySource(ResumableSource[RetentlySourceConfig, RetentlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETENTLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RETENTLY,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Retently",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["nps", "csat", "ces", "survey", "customer feedback"],
            caption="""Enter your Retently API key to pull your customer feedback data into the PostHog Data warehouse.

You can create an API key under **Settings → Integrations → API** in [Retently](https://app.retently.com). A key with **read** permission is sufficient — this source only performs GET requests.
""",
            iconPath="/static/services/retently.png",
            docsUrl="https://posthog.com/docs/cdp/sources/retently",
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.retently.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.retently.com": "Your Retently API key is invalid or has been revoked. Generate a new key under Settings → Integrations → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.retently.com": "Your Retently API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: RetentlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only feedback supports incremental sync — its `startDate` query param filters responses
        # server-side by creation date. See settings.py for why the other endpoints are full
        # refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: RetentlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single /ping probe validates access to every schema.
        return validate_retently_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RetentlyResumeConfig]:
        return ResumableSourceManager[RetentlyResumeConfig](inputs, RetentlyResumeConfig)

    def source_for_pipeline(
        self,
        config: RetentlySourceConfig,
        resumable_source_manager: ResumableSourceManager[RetentlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in RETENTLY_ENDPOINTS:
            raise ValueError(f"Unknown Retently schema '{inputs.schema_name}'")

        return retently_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
