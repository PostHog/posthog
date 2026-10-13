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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.poplar import PoplarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.poplar import (
    PoplarResumeConfig,
    poplar_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PoplarSource(ResumableSource[PoplarSourceConfig, PoplarResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.heypoplar.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POPLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POPLAR,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Poplar",
            iconPath="/static/services/poplar.png",
            docsUrl="https://posthog.com/docs/cdp/sources/poplar",
            keywords=["direct mail", "postcards"],
            caption="Enter a production access token from the [API page](https://app.heypoplar.com/credentials) "
            "of your Poplar account. Test tokens can only send mailings, so they can't read data. "
            "Poplar lists active campaigns only, so creatives and mailings sync for active campaigns.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_schemas(
        self,
        config: PoplarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Appending would add a duplicate row each time a mailing changes state, so only merge is offered.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=INCREMENTAL_FIELDS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.canonical_descriptions import (  # noqa: PLC0415 - load descriptions only when enrichment needs them
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: PoplarSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.access_token)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.heypoplar.com": AUTH_ERROR,
            "403 Client Error: Forbidden for url: https://api.heypoplar.com": AUTH_ERROR,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PoplarResumeConfig]:
        return ResumableSourceManager(inputs, PoplarResumeConfig)

    def source_for_pipeline(
        self,
        config: PoplarSourceConfig,
        resumable_source_manager: ResumableSourceManager[PoplarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return poplar_source(config.access_token, inputs, resumable_source_manager)
