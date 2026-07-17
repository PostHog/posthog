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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JumpcloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.jumpcloud import (
    JumpcloudResumeConfig,
    jumpcloud_source,
    validate_credentials as validate_jumpcloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    JUMPCLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JumpcloudSource(ResumableSource[JumpcloudSourceConfig, JumpcloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUMPCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # Both fields retarget the stored API key, so changing either forces secret re-entry:
        # `org_id` selects which organization the key acts on, and `region` selects which
        # regional JumpCloud host the key is sent to.
        return ["org_id", "region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JUMPCLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="JumpCloud",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your JumpCloud admin API key to sync your directory and activity data into the PostHog Data warehouse.

Find your API key in the JumpCloud Admin Portal: click your account initials in the top-right corner and select **My API Key**.

The `events` table requires a Directory Insights subscription. If you're an MSP/MTP admin managing multiple organizations, also enter the organization ID the key should act on.""",
            iconPath="/static/services/jumpcloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jumpcloud",
            keywords=["iam", "sso", "directory insights"],
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (console.jumpcloud.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (console.eu.jumpcloud.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID (optional, MSP/MTP only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked API key surfaces as a requests HTTPError when `_request`
        # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
        # the sync. Matched on the stable status text only, since the host varies by region
        # and API family (console vs Directory Insights).
        return {
            "401 Client Error": "Your JumpCloud API key is invalid or has been revoked. Generate a new key in the JumpCloud Admin Portal (account menu → My API Key), then reconnect.",
            "403 Client Error": "Your JumpCloud API key does not have permission to read this data. Check the admin's role permissions (and Directory Insights subscription for the events table), then reconnect.",
        }

    def get_schemas(
        self,
        config: JumpcloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only Directory Insights events expose a server-side time filter (start_time), so
        # only that stream is incremental. Merge-only: the start_time boundary may re-return
        # the watermark row, and merge dedupes it on `id` where append would duplicate it.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=[JUMPCLOUD_ENDPOINTS[endpoint].primary_key],
                description=(
                    "Directory Insights activity events (console, SSO, RADIUS, LDAP, systems, and directory changes). "
                    "Only syncs the last 90 days on initial sync, bounded by your Directory Insights retention"
                    if endpoint == "events"
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: JumpcloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_jumpcloud_credentials(config.api_key, config.org_id, config.region, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JumpcloudResumeConfig]:
        return ResumableSourceManager[JumpcloudResumeConfig](inputs, JumpcloudResumeConfig)

    def source_for_pipeline(
        self,
        config: JumpcloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[JumpcloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return jumpcloud_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            org_id=config.org_id,
            region=config.region,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
