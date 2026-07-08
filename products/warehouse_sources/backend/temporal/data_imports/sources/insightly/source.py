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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InsightlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.insightly import (
    InsightlyResumeConfig,
    insightly_source,
    normalize_pod,
    validate_credentials as validate_insightly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import (
    ENDPOINTS,
    INSIGHTLY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InsightlySource(ResumableSource[InsightlySourceConfig, InsightlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INSIGHTLY

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to `api.{pod}.insightly.com`; retargeting the pod must
        # re-require the key so it can't be exfiltrated to another instance.
        return ["pod"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INSIGHTLY,
            category=DataWarehouseSourceCategory.CRM,
            label="Insightly",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Insightly API key to sync your Insightly CRM data into the PostHog Data warehouse.

Find your **API key** and your **API URL** in Insightly under **User Settings** (top-right profile menu). The API URL looks like `https://api.na1.insightly.com/v3.1` — the **pod** is the region token in the middle (`na1`, `eu1`, ...). Enter just that token, or paste the full API URL.

The API key inherits your Insightly user's permissions, so make sure your user can access the data you want to sync.""",
            iconPath="/static/services/insightly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/insightly",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="pod",
                        label="Pod (instance)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="na1",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError when `fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync.
            "401 Client Error": "Your Insightly API key is invalid or has been revoked. Generate a new key in Insightly User Settings, then reconnect.",
            "403 Client Error": "Your Insightly user lacks permission for this data. Check your user's access in Insightly, then reconnect.",
        }

    def get_schemas(
        self,
        config: InsightlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = INSIGHTLY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                detected_primary_keys=[endpoint_config.primary_key],
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InsightlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        path = INSIGHTLY_ENDPOINTS[schema_name].path if schema_name in INSIGHTLY_ENDPOINTS else "/Contacts"
        try:
            status = validate_insightly_credentials(config.pod, config.api_key, path)
        except ValueError as e:
            return False, str(e)

        if status is not None and 200 <= status < 300:
            return True, None
        # A valid key may lack scope for some endpoints; accept that at source-create
        # (schema_name is None) and only reject when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status in (401, 403):
            return False, "Invalid Insightly API key or insufficient permissions"
        return False, "Could not validate Insightly credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InsightlyResumeConfig]:
        return ResumableSourceManager[InsightlyResumeConfig](inputs, InsightlyResumeConfig)

    def source_for_pipeline(
        self,
        config: InsightlySourceConfig,
        resumable_source_manager: ResumableSourceManager[InsightlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return insightly_source(
            pod=normalize_pod(config.pod),
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
