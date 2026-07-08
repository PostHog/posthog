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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RootlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.rootly import (
    RootlyResumeConfig,
    probe_credentials,
    rootly_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.settings import ENDPOINTS, ROOTLY_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RootlySource(ResumableSource[RootlySourceConfig, RootlyResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROOTLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROOTLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Rootly",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Rootly API key to automatically pull your Rootly incident-management data into the PostHog Data warehouse.

You can create an API key in your [Rootly account settings](https://rootly.com/account/api_keys). A Global-scope key can read every resource; Team- and User-scope keys only see the resources they are granted.""",
            iconPath="/static/services/rootly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/rootly",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="rootly_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # No retry can satisfy a credential/scope problem. Match the stable status text + base
            # host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.rootly.com": "Your Rootly API key is invalid or has been revoked. Create a new API key in your Rootly account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.rootly.com": "Your Rootly API key is missing access to this resource. Grant the key access in your Rootly account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: RootlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ROOTLY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: RootlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = probe_credentials(config.api_key, schema_name)

        if status == 200:
            return True, None
        # At source-create (schema_name is None) a 403 means the token is genuine but scoped away
        # from the probe resource — accept it; per-endpoint scope is checked when configuring a schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 401:
            return False, "Your Rootly API key is invalid or has been revoked."
        if status == 403:
            return False, "Your Rootly API key does not have access to this resource."
        return False, "Could not validate your Rootly API key. Please check the key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RootlyResumeConfig]:
        return ResumableSourceManager[RootlyResumeConfig](inputs, RootlyResumeConfig)

    def source_for_pipeline(
        self,
        config: RootlySourceConfig,
        resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rootly_source(
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
