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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.modal import ModalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.modal import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    ModalResumeConfig,
    modal_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.modal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ModalSource(ResumableSource[ModalSourceConfig, ModalResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://modal.com/docs/sdk/py/latest/Workspace#billingreport"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MODAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MODAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Modal",
            iconPath="/static/services/modal.png",
            caption=(
                "Create a token in [Modal settings](https://modal.com/settings). "
                "Use a service-user token with workspace billing access. "
                "A Team or Enterprise plan is required for [Workspace billing reports](https://modal.com/docs/sdk/py/latest/Workspace#billingreport). "
                "The first sync imports 365 days of daily reports or 30 days of hourly reports."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="token_id",
                        label="Token ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ak-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="token_secret",
                        label="Token secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="as-...",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {AUTH_ERROR: AUTH_ERROR, PERMISSION_ERROR: PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ModalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: ModalSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ModalResumeConfig]:
        return ResumableSourceManager(inputs, ModalResumeConfig)

    def source_for_pipeline(
        self,
        config: ModalSourceConfig,
        resumable_source_manager: ResumableSourceManager[ModalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return modal_source(config, inputs, resumable_source_manager)
