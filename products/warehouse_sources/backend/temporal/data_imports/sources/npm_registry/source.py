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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry import (
    NpmRegistryResumeConfig,
    npm_registry_source,
    validate_packages,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NPM_REGISTRY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NpmRegistrySource(ResumableSource[NpmRegistrySourceConfig, NpmRegistryResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://github.com/npm/registry/blob/master/docs/download-counts.md"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NPMREGISTRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NPM_REGISTRY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="npm registry",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["npm", "node", "javascript", "downloads"],
            caption="""Pull daily download counts and published-version metadata for npm packages from the public npm registry into the PostHog Data warehouse.

npm's read APIs are public, so no credentials are required. There is no practical way to sync the whole registry, so enter the package names you want to track, one per line (or comma-separated). For example:

```
react
@slack/client
lodash
```

Daily download counts only go back to 2015-01-10 and are fetched in windows, so the first sync of a long-lived package can take a while. The registry has no server-side "changed since" filter for version metadata, so the Versions table always syncs as a full refresh.""",
            iconPath="/static/services/npm_registry.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="package_names",
                        label="Package names",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="react\n@slack/client\nlodash",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # npm's read APIs are unauthenticated, so there are no credential errors to permanently
        # fail on. A missing package surfaces as a 404 and is skipped per-package during the sync.
        return {}

    def get_schemas(
        self,
        config: NpmRegistrySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=NPM_REGISTRY_ENDPOINTS[endpoint].should_sync_default,
                description=NPM_REGISTRY_ENDPOINTS[endpoint].description,
                detected_primary_keys=NPM_REGISTRY_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: NpmRegistrySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_packages(config.package_names)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NpmRegistryResumeConfig]:
        return ResumableSourceManager[NpmRegistryResumeConfig](inputs, NpmRegistryResumeConfig)

    def source_for_pipeline(
        self,
        config: NpmRegistrySourceConfig,
        resumable_source_manager: ResumableSourceManager[NpmRegistryResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return npm_registry_source(
            endpoint=inputs.schema_name,
            package_names=config.package_names,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
