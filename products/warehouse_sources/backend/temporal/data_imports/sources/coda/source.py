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
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.coda import (
    coda_source,
    validate_credentials as validate_coda_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodaSource(SimpleSource[CodaSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://coda.io/developers/apis/v1"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://coda.io": "Coda authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://coda.io": "Coda denied access. Please check that your API token can read the requested docs.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Coda",
            caption="""Enter your Coda API token to pull your docs, tables, and rows into the PostHog Data warehouse.

You can generate an API token in [Coda account settings](https://coda.io/account). The token only sees docs its creator can access. Rows are synced from every table of every doc — note Coda's doc-listing rate limit makes large workspaces slow to sync.""",
            iconPath="/static/services/coda.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coda",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coda.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CodaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Coda's list endpoints have no updated-since filters; full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CodaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_coda_credentials(config.api_token):
            return True, None

        return False, "Invalid Coda API token"

    def source_for_pipeline(self, config: CodaSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return coda_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
