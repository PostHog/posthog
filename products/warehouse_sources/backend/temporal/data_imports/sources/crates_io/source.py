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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.crates_io import (
    crates_io_source,
    validate_credentials as validate_crates_io_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.settings import (
    CRATES_IO_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CratesIOSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CratesIOSource(SimpleSource[CratesIOSourceConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://doc.rust-lang.org/cargo/reference/registry-web-api.html"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRATESIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CRATES_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="crates.io",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["rust", "cargo", "crates"],
            caption="""Pull metadata, versions, owners, and daily download counts for Rust crates from the [crates.io](https://crates.io) API into the PostHog Data warehouse.

crates.io's read APIs are public, so no credentials are required. There is no practical way to sync the whole registry, so enter the crate names you want to track, one per line (or comma-separated). For example:

```
serde
tokio
posthog-rs
```

Each sync fetches the current data for every configured crate. crates.io has no server-side "changed since" filter, and daily download counts only cover the trailing ~90 days, so all tables sync as a full refresh.""",
            iconPath="/static/services/crates_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/crates-io",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="crates",
                        label="Crates",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="serde\ntokio\nposthog-rs",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # crates.io's read APIs are unauthenticated, so there are no credential errors to
        # permanently fail on. A missing crate surfaces as a 404 and is skipped per-crate during
        # the sync.
        return {}

    def get_schemas(
        self,
        config: CratesIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # crates.io exposes no server-side timestamp filter, so no stream is truly
                # incremental; re-fetching would only duplicate immutable history, so append is
                # off too.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=CRATES_IO_ENDPOINTS[endpoint].should_sync_default,
                description=CRATES_IO_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: CratesIOSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_crates_io_credentials(config.crates)

    def source_for_pipeline(self, config: CratesIOSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return crates_io_source(
            endpoint=inputs.schema_name,
            crates_raw=config.crates,
            logger=inputs.logger,
        )
