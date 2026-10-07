from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.develocity import (
    DevelocityResumeConfig,
    develocity_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.settings import (
    API_DOCS_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INVALID_KEY,
    MISSING_PERMISSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.develocity import (
    DevelocitySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DevelocitySource(ResumableSource[DevelocitySourceConfig, DevelocityResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEVELOCITY

    @property
    def connection_host_fields(self) -> list[str]:
        return ["instance_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": INVALID_KEY, "403 Client Error": MISSING_PERMISSION}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DevelocitySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS.keys())

    def validate_credentials(
        self,
        config: DevelocitySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DevelocityResumeConfig]:
        return ResumableSourceManager(inputs, DevelocityResumeConfig)

    def source_for_pipeline(
        self,
        config: DevelocitySourceConfig,
        resumable_source_manager: ResumableSourceManager[DevelocityResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return develocity_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEVELOCITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Develocity",
            caption="Generate an access key in Develocity under My settings > Access keys. "
            'The account needs the "Access build data via the API" permission.',
            docsUrl=API_DOCS_URL,
            iconPath="/static/services/develocity.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://develocity.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
