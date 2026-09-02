from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.decagon import (
    DecagonResumeConfig,
    decagon_source,
    validate_credentials as validate_decagon_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import DECAGON_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.decagon import (
    DecagonSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DecagonSource(ResumableSource[DecagonSourceConfig, DecagonResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.decagon.ai/api-reference/getting-started"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DECAGON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DECAGON,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Decagon",
            caption="""Enter a Decagon API key to pull your Decagon conversations into the PostHog Data warehouse.

You can find your API key on the **Developer** page of the [Decagon dashboard](https://decagon.ai/).
""",
            iconPath="/static/services/decagon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/decagon",
            keywords=["ai agents", "customer support", "conversations", "csat"],
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
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Decagon rejected the API key. Generate a new key on the Developer page of the "
                "Decagon dashboard and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The Decagon API key does not have access to the endpoint behind this table. Check "
                "the key on the Developer page of the Decagon dashboard and reconnect."
            ),
        }

    def get_retryable_errors(self) -> set[str]:
        # `fetch_page` (decagon.py) already retries `DecagonRetryableError` (429/5xx),
        # `requests.ReadTimeout`, and `requests.ConnectionError` with backoff; if that budget
        # still exhausts, Temporal retries the whole activity, so the failure is transient and
        # self-recovering. Match the host rather than the per-endpoint path, so a timeout or
        # dropped connection on any Decagon endpoint is covered.
        return {
            "HTTPSConnectionPool(host='api.decagon.ai', port=443)",
            "Decagon API error (retryable)",
        }

    def get_schemas(
        self,
        config: DecagonSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Incremental writes merge on the primary key, so a keyless stream can
                # only offer append (gated per endpoint) or full refresh.
                supports_incremental=endpoint_config.primary_keys is not None
                and len(endpoint_config.incremental_fields) > 0,
                supports_append=endpoint_config.supports_append and len(endpoint_config.incremental_fields) > 0,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
            )
            for endpoint, endpoint_config in DECAGON_ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: DecagonSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_decagon_credentials(config.api_key):
            return True, None

        return False, "Invalid Decagon API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DecagonResumeConfig]:
        return ResumableSourceManager[DecagonResumeConfig](inputs, DecagonResumeConfig)

    def source_for_pipeline(
        self,
        config: DecagonSourceConfig,
        resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return decagon_source(
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
