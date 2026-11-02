from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.schematic import (
    SchematicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.schematic import (
    SchematicResumeConfig,
    schematic_source,
    validate_credentials as validate_schematic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SchematicSource(ResumableSource[SchematicSourceConfig, SchematicResumeConfig]):
    codebase_detection = detect(
        env=("^SCHEMATIC_",),
        npm=(
            "@schematichq/schematic-js",
            "@schematichq/schematic-react",
            "@schematichq/schematic-components",
            "@schematichq/schematic-typescript-node",
        ),
        pypi=("schematichq",),
        go=("github.com/SchematicHQ/schematic-go",),
        rubygems=("schematic",),
        composer=("schematichq/schematic-php",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.schematichq.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCHEMATIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCHEMATIC,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Schematic",
            keywords=["schematichq", "entitlements"],
            caption="""Sync your Schematic companies, users, features, flags, plans, entitlements and billing catalog into the PostHog Data warehouse.

Use a secret API key for the environment you want to sync, created under **Settings > API keys** in Schematic. Publishable keys can't list data.""",
            iconPath="/static/services/schematic.png",
            docsUrl="https://posthog.com/docs/cdp/sources/schematic",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sch_prod_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.schematichq.com": "Schematic rejected your API key. Create a new secret key under Settings > API keys, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.schematichq.com": "Your Schematic API key can't read this data. Use a secret key for the environment you want to sync, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: SchematicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SchematicSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = validate_schematic_credentials(config.api_key)
        if is_valid:
            return True, None
        if status in (401, 403):
            return False, "Schematic rejected the API key. Use a secret key for the environment you want to sync."
        return False, "Could not reach the Schematic API with that key. Check the key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SchematicResumeConfig]:
        return ResumableSourceManager[SchematicResumeConfig](inputs, SchematicResumeConfig)

    def source_for_pipeline(
        self,
        config: SchematicSourceConfig,
        resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return schematic_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
