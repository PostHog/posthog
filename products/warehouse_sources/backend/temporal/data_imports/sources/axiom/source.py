from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.axiom import (
    AxiomResumeConfig,
    axiom_source,
    validate_credentials as validate_axiom_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.axiom.settings import (
    API_VERSION,
    AUTH_ERRORS,
    ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.axiom import AxiomSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AxiomSource(ResumableSource[AxiomSourceConfig, AxiomResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://axiom.co/docs/restapi/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AXIOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in AUTH_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AxiomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: AxiomSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_axiom_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AxiomResumeConfig]:
        return ResumableSourceManager(inputs, AxiomResumeConfig)

    def source_for_pipeline(
        self,
        config: AxiomSourceConfig,
        resumable_source_manager: ResumableSourceManager[AxiomResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return axiom_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AXIOM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Axiom",
            iconPath="/static/services/axiom.png",
            caption=(
                "Create an advanced API token in Axiom Settings > API tokens. "
                "Grant read access to the resources you want to sync and query access to their datasets. "
                "This source imports monitoring and configuration data."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xaat-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="example-org",
                        secret=False,
                        caption="Required for personal access tokens. Find this ID in Axiom Settings > General.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
