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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZoomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom import (
    ZoomResumeConfig,
    validate_credentials as validate_zoom_credentials,
    zoom_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZoomSource(ResumableSource[ZoomSourceConfig, ZoomResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOOM

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Zoom authentication failed. Please check your account ID, client ID, and client secret.",
            "Invalid access token": "Zoom authentication failed. Please reconnect the source.",
            "403 Client Error": "Your Zoom app is missing the required scopes. Grant user/meeting/webinar read scopes and reconnect.",
        }

    def get_schemas(
        self,
        config: ZoomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Zoom's list endpoints expose no server-side timestamp filter, so every
        # endpoint is a full refresh (no incremental sync).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ZoomSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_zoom_credentials(
            account_id=config.account_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZoomResumeConfig]:
        return ResumableSourceManager[ZoomResumeConfig](inputs, ZoomResumeConfig)

    def source_for_pipeline(
        self,
        config: ZoomSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZoomResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zoom_source(
            account_id=config.account_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZOOM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Zoom",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Zoom users, meetings, and webinars into the PostHog Data warehouse.

Create a **Server-to-Server OAuth** app in the [Zoom App Marketplace](https://marketplace.zoom.us/develop/create) and copy its Account ID, Client ID, and Client Secret below.

Grant the following read scopes:
- `user:read:list_users:admin`
- `meeting:read:list_meetings:admin`
- `webinar:read:list_webinars:admin`
""",
            iconPath="/static/services/zoom.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zoom",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
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
                ],
            ),
        )
