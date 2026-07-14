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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PyPISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.pypi import (
    pypi_source,
    validate_credentials as validate_pypi_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PYPI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PyPISource(SimpleSource[PyPISourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PYPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PY_PI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="PyPI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull metadata for Python packages from the [PyPI](https://pypi.org) JSON API into the PostHog Data warehouse.

PyPI's read APIs are public, so no credentials are required. There is no list endpoint, so enter the package names you want to track, one per line (or comma-separated). For example:

```
requests
django
posthog
```

Each sync fetches the current metadata for every configured package. PyPI has no server-side "changed since" filter, so all tables sync as a full refresh.""",
            iconPath="/static/services/pypi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pypi",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="packages",
                        label="Packages",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="requests\ndjango\nposthog",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # PyPI's read APIs are unauthenticated, so there are no credential errors to permanently fail
        # on. A missing package surfaces as a 404 and is skipped per-package during the sync.
        return {}

    def get_schemas(
        self,
        config: PyPISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # PyPI exposes no server-side timestamp filter, so no stream is truly incremental;
                # re-fetching would only duplicate immutable history, so append is off too.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=PYPI_ENDPOINTS[endpoint].should_sync_default,
                description=PYPI_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PyPISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_pypi_credentials(config.packages)

    def source_for_pipeline(self, config: PyPISourceConfig, inputs: SourceInputs) -> SourceResponse:
        return pypi_source(
            endpoint=inputs.schema_name,
            packages_raw=config.packages,
            logger=inputs.logger,
        )
