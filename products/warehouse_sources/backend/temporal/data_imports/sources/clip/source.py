from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.clip import (
    ClipResumeConfig,
    clip_source,
    parse_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clip import ClipSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClipSource(ResumableSource[ClipSourceConfig, ClipResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://developer.clip.mx/reference/transactions"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLIP

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClipSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only={"transactions"},
            should_sync_default={"settlements": False, "settlement_payments": False},
        )

    def validate_credentials(
        self,
        config: ClipSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            parse_start_date(config.start_date)
        except ValueError as error:
            return False, str(error)
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClipResumeConfig]:
        return ResumableSourceManager(inputs, ClipResumeConfig)

    def source_for_pipeline(
        self,
        config: ClipSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClipResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clip_source(config, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLIP,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Clip (PayClip S. de R.L. de C.V.)",
            iconPath="/static/services/clip.png",
            caption=(
                "Create an API key and secret key in the [Clip developer dashboard](https://dashboard.clip.mx/dashboard). "
                "Transactions sync from the start date. Incremental sync uses the creation date; "
                "use a full refresh to capture changes to older transactions. "
                "Deposit tables contain the last 90 days and require deposits API access. "
                "Clip accounts with Cuenta Digital cannot use the deposits API."
            ),
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
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
