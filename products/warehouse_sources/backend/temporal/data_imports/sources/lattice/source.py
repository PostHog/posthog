from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LatticeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import (
    LatticeResumeConfig,
    lattice_source,
    validate_credentials as validate_lattice_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LatticeSource(ResumableSource[LatticeSourceConfig, LatticeResumeConfig]):
    api_docs_url = "https://developers.lattice.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LATTICE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.latticehq.com": "Lattice authentication failed. Please check your API key.",
            "401 Client Error: Unauthorized for url: https://api.emea.latticehq.com": "Lattice authentication failed. Please check your API key (and that it matches the selected region).",
            "403 Client Error: Forbidden for url: https://api.latticehq.com": "Lattice denied access. API keys inherit the creating user's privileges — please check the key owner can access this data.",
            "403 Client Error: Forbidden for url: https://api.emea.latticehq.com": "Lattice denied access. API keys inherit the creating user's privileges — please check the key owner can access this data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LATTICE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Lattice",
            caption="""Enter your Lattice API key to pull your Lattice performance management data into the PostHog Data warehouse.

A Lattice admin can generate an API key under Admin > Settings > API Keys (Lattice may require requesting API access first). Pick the region that matches your Lattice data residency.""",
            iconPath="/static/services/lattice.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lattice",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.latticehq.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EMEA (api.emea.latticehq.com)", value="emea"),
                        ],
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

    def get_schemas(
        self,
        config: LatticeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No Lattice list endpoint exposes a server-side timestamp filter;
        # full refresh only.
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
        self, config: LatticeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_lattice_credentials(config.region, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LatticeResumeConfig]:
        return ResumableSourceManager[LatticeResumeConfig](inputs, LatticeResumeConfig)

    def source_for_pipeline(
        self,
        config: LatticeSourceConfig,
        resumable_source_manager: ResumableSourceManager[LatticeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lattice_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
