from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.amplemarket import (
    AmplemarketResumeConfig,
    amplemarket_source,
    validate_credentials as validate_amplemarket_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.settings import (
    BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplemarket import (
    AmplemarketSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmplemarketSource(ResumableSource[AmplemarketSourceConfig, AmplemarketResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://docs.amplemarket.com/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMPLEMARKET

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return auth_non_retryable_errors(BASE_URL, service="Amplemarket")

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMPLEMARKET,
            category=DataWarehouseSourceCategory.SALES,
            label="Amplemarket",
            caption="""Enter your Amplemarket API key to pull your Amplemarket data into the PostHog Data warehouse.

You can generate an API key from your Amplemarket dashboard. See the [Amplemarket quickstart guide](https://docs.amplemarket.com/guides/quickstart) for details.""",
            iconPath="/static/services/amplemarket.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amplemarket",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amplemarket.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmplemarketSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AmplemarketSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_amplemarket_credentials(config.api_key):
            return True, None

        return False, "Invalid Amplemarket API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AmplemarketResumeConfig]:
        return ResumableSourceManager[AmplemarketResumeConfig](inputs, AmplemarketResumeConfig)

    def source_for_pipeline(
        self,
        config: AmplemarketSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmplemarketResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amplemarket_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
