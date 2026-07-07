from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MixpanelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.mixpanel import (
    MixpanelResumeConfig,
    mixpanel_source,
    validate_credentials as validate_mixpanel_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUPPORTS_INCREMENTAL,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MixpanelSource(ResumableSource[MixpanelSourceConfig, MixpanelResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIXPANEL

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host and `project_id` the project the stored service-account secret is
        # sent to; retargeting either must re-require the secret so it can't be aimed elsewhere.
        return ["region", "project_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MIXPANEL,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Mixpanel",
            caption="""Connect your Mixpanel project to pull events, user profiles, cohorts and annotations into the PostHog Data warehouse.

Authenticate with a [Mixpanel Service Account](https://developer.mixpanel.com/reference/service-accounts). In Mixpanel, go to **Organization Settings → Service Accounts → Create Service Account** and grant it access to the project you want to sync. You'll need:

- The service account **username** and **secret**
- Your numeric **Project ID** (found under **Project Settings**)
- The **data residency region** your project lives in (US, EU or India)
""",
            iconPath="/static/services/mixpanel.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mixpanel",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data residency region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (mixpanel.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu.mixpanel.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="India (in.mixpanel.com)", value="in"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="service_account_username",
                        label="Service account username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-service-account.abc123.mp-service-account",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="service_account_secret",
                        label="Service account secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mixpanel.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MixpanelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in SUPPORTS_INCREMENTAL,
                supports_append=endpoint in SUPPORTS_INCREMENTAL,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Only syncs the last 365 days on initial sync" if endpoint == "export" else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MixpanelSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_mixpanel_credentials(
            region=config.region,
            username=config.service_account_username,
            secret=config.service_account_secret,
            project_id=config.project_id,
            schema_name=schema_name,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Mixpanel rejected the service account credentials. Create a new service account in "
                "Organization Settings and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The Mixpanel service account does not have access to this project or resource. Grant it "
                "access to the project and reconnect."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MixpanelResumeConfig]:
        return ResumableSourceManager[MixpanelResumeConfig](inputs, MixpanelResumeConfig)

    def source_for_pipeline(
        self,
        config: MixpanelSourceConfig,
        resumable_source_manager: ResumableSourceManager[MixpanelResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mixpanel_source(
            region=config.region,
            username=config.service_account_username,
            secret=config.service_account_secret,
            project_id=config.project_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
