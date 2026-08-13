from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketo import (
    MarketoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.marketo import (
    MarketoResumeConfig,
    marketo_source,
    validate_credentials as validate_marketo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MarketoSource(ResumableSource[MarketoSourceConfig, MarketoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Marketo has shipped one REST version since launch and exposes no version selector, so the
    # `/rest/v1` path segment is not a pinnable version.
    api_docs_url = "https://developer.adobe.com/marketo-apis/api/mapi/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MARKETO

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Marketo authentication failed": "PostHog could not authenticate with Marketo. Check the client ID and secret on your Marketo custom service, and make sure the service is still active.",
            "Marketo API error 601": "Your Marketo access token is invalid. Reconnect the source with a fresh client ID and secret.",
            "Marketo API error 603": "Your Marketo custom service does not have permission for this data. Add the missing API role permissions in Marketo and try again.",
            "Marketo API error 607": "Your Marketo instance hit its daily API quota. The sync will run again once the quota resets.",
            "Invalid Marketo Munchkin account ID": "The Munchkin account ID doesn't look right. Copy it from Marketo under Admin, Web Services.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MARKETO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Marketo",
            caption="""Connect Adobe Marketo Engage to pull your leads, activities, campaigns, and program assets into the PostHog Data warehouse.

In Marketo, open **Admin → Web Services** for your Munchkin account ID, then **Admin → LaunchPoint** to create a custom service and copy its client ID and secret. The service's API role needs read access to leads, activities, campaigns, and assets.

Leads and activities come through Marketo's Bulk Extract API, so the first sync backfills from the start date you set below.""",
            iconPath="/static/services/marketo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/marketo",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["adobe marketo", "marketo engage"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="munchkin_id",
                        label="Munchkin account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123-ABC-456",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: MarketoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MarketoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_marketo_credentials(config.munchkin_id, config.client_id, config.client_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MarketoResumeConfig]:
        return ResumableSourceManager[MarketoResumeConfig](inputs, MarketoResumeConfig)

    def source_for_pipeline(
        self,
        config: MarketoSourceConfig,
        resumable_source_manager: ResumableSourceManager[MarketoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return marketo_source(
            munchkin_id=config.munchkin_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            start_date=config.start_date,
        )
