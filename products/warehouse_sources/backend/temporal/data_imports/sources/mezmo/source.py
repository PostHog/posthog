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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mezmo import MezmoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.mezmo import (
    MezmoResumeConfig,
    mezmo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.settings import (
    ENDPOINTS,
    INVALID_KEY_MESSAGE,
    PERMISSION_MESSAGE,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MezmoSource(ResumableSource[MezmoSourceConfig, MezmoResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.mezmo.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEZMO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_KEY_MESSAGE,
            "403 Client Error": PERMISSION_MESSAGE,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MezmoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: MezmoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MezmoResumeConfig]:
        return ResumableSourceManager(inputs, MezmoResumeConfig)

    def source_for_pipeline(
        self,
        config: MezmoSourceConfig,
        resumable_source_manager: ResumableSourceManager[MezmoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mezmo_source(
            config,
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            inputs.team_id,
            inputs.job_id,
            resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEZMO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mezmo (formerly LogDNA)",
            caption="Import pipelines, component alerts, and pipeline health. "
            "In Mezmo, open **Settings > Organization > API Keys** and create a service account. "
            "Use its IAM access key with read access to pipelines and alerts. "
            "For an enterprise key, also enter the delegated account ID.",
            iconPath="/static/services/mezmo.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="IAM access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sts_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Delegated account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
