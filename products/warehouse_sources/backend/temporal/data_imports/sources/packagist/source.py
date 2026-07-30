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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PackagistSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.packagist import (
    PackagistResumeConfig,
    packagist_source,
    validate_credentials as validate_packagist_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PACKAGIST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PackagistSource(ResumableSource[PackagistSourceConfig, PackagistResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://packagist.org/apidoc"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PACKAGIST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PACKAGIST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Packagist",
            keywords=["composer", "php"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull metadata, download statistics, and security advisories for PHP packages from [Packagist](https://packagist.org) (the Composer package registry) into the PostHog Data warehouse.

Packagist's read APIs are public, so no credentials are required. Enter the packages you want to track, one per line (or comma-separated), as `vendor/package` names. A bare vendor name syncs every package published by that vendor. For example:

```
monolog/monolog
symfony/console
yourvendor
```

Download statistics sync incrementally per day; the other tables sync as a full refresh.""",
            iconPath="/static/services/packagist.png",
            docsUrl="https://posthog.com/docs/cdp/sources/packagist",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="packages",
                        label="Packages",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="monolog/monolog\nsymfony/console\nyourvendor",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.packagist.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Packagist's read APIs are unauthenticated, so there are no credential errors to
        # permanently fail on. A missing package surfaces as a 404 and is skipped per-package.
        return {}

    def get_schemas(
        self,
        config: PackagistSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=PACKAGIST_ENDPOINTS[endpoint].supports_incremental,
                supports_append=PACKAGIST_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=PACKAGIST_ENDPOINTS[endpoint].should_sync_default,
                description=PACKAGIST_ENDPOINTS[endpoint].description,
                default_incremental_lookback_seconds=PACKAGIST_ENDPOINTS[endpoint].default_incremental_lookback_seconds,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PackagistSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_packagist_credentials(config.packages)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PackagistResumeConfig]:
        return ResumableSourceManager[PackagistResumeConfig](inputs, PackagistResumeConfig)

    def source_for_pipeline(
        self,
        config: PackagistSourceConfig,
        resumable_source_manager: ResumableSourceManager[PackagistResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return packagist_source(
            endpoint=inputs.schema_name,
            packages_raw=config.packages,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
