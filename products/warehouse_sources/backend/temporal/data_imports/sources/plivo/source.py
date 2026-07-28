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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.plivo import PlivoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.plivo import (
    PlivoResumeConfig,
    plivo_source,
    validate_credentials as validate_plivo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLIVO_BASE_URL,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlivoSource(ResumableSource[PlivoSourceConfig, PlivoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.plivo.com/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLIVO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLIVO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Plivo",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["sms", "voice", "cpaas"],
            caption=(
                "Enter your Plivo Auth ID and Auth Token to sync your SMS message and voice call "
                "detail records into the PostHog Data warehouse. Both are shown on the overview page "
                "of the [Plivo console](https://console.plivo.com/dashboard/).\n\n"
                "Plivo retains message and call records for **90 days**, so syncing them into the "
                "warehouse lets you keep history beyond that window."
            ),
            iconPath="/static/services/plivo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/plivo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_id",
                        label="Auth ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="MAXXXXXXXXXXXXXXXXXX",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.plivo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Plivo returns 401 for a bad Auth ID/Token pair and 403 for a valid credential that lacks
        # access to the resource; neither can succeed on retry.
        auth_message = (
            "Plivo authentication failed. Check the Auth ID and Auth Token from your Plivo console and reconnect."
        )
        return {
            f"401 Client Error: Unauthorized for url: {PLIVO_BASE_URL}": auth_message,
            f"403 Client Error: Forbidden for url: {PLIVO_BASE_URL}": (
                "Your Plivo credentials don't have access to this resource. "
                "Check the account's permissions in the Plivo console."
            ),
        }

    def get_schemas(
        self,
        config: PlivoSourceConfig,
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
            descriptions=ENDPOINT_DESCRIPTIONS,
        )

    def validate_credentials(
        self, config: PlivoSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_plivo_credentials(config.auth_id, config.auth_token):
            return True, None

        return False, "Invalid Plivo Auth ID or Auth Token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlivoResumeConfig]:
        return ResumableSourceManager[PlivoResumeConfig](inputs, PlivoResumeConfig)

    def source_for_pipeline(
        self,
        config: PlivoSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlivoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return plivo_source(
            auth_id=config.auth_id,
            auth_token=config.auth_token,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
