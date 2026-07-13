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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KatanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.katana import (
    KatanaResumeConfig,
    katana_source,
    validate_credentials as validate_katana_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KatanaSource(ResumableSource[KatanaSourceConfig, KatanaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KATANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KATANA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Katana",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["katana", "mrp", "erp", "inventory", "manufacturing"],
            caption="""Enter your Katana API key to sync your Katana Cloud Inventory (MRP) data into the PostHog Data warehouse.

Generate an API key in Katana under **Settings > API** (an active API access add-on / Professional plan is required). The key is sent as a Bearer token and has read access to your factory's data.""",
            iconPath="/static/services/katana.png",
            docsUrl="https://posthog.com/docs/cdp/sources/katana",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Katana API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.katana.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A revoked/invalid key surfaces as a requests HTTPError raised by `_request_page` with a
            # scrubbed URL. Retrying can't fix a credential problem, so stop the sync. Match the stable
            # status + base host (the scrubbed URL keeps this prefix free of the key).
            "401 Client Error: Unauthorized for url: https://api.katanamrp.com": "Your Katana API key is invalid or has been revoked. Generate a new key under Settings > API in Katana, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.katanamrp.com": "Your Katana API key is missing access to this data. Check the key's permissions in Katana, then reconnect.",
        }

    def get_schemas(
        self,
        config: KatanaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KatanaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_katana_credentials(config.api_key):
            return True, None

        return False, "Invalid Katana API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KatanaResumeConfig]:
        return ResumableSourceManager[KatanaResumeConfig](inputs, KatanaResumeConfig)

    def source_for_pipeline(
        self,
        config: KatanaSourceConfig,
        resumable_source_manager: ResumableSourceManager[KatanaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return katana_source(
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
