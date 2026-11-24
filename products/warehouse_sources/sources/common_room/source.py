from typing import Optional, cast

from products.warehouse_sources.sources.common_room._config import CommonRoomSourceConfig
from products.warehouse_sources.sources.common_room.common_room import (
    INVALID_TOKEN_MESSAGE,
    CommonRoomResumeConfig,
    common_room_source,
    validate_credentials as validate_common_room_credentials,
)
from products.warehouse_sources.sources.common_room.settings import (
    ACTIVITIES_LOOKBACK_DAYS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "CommonRoom"


@SourceRegistry.register
class CommonRoomSource(ResumableSource[CommonRoomSourceConfig, CommonRoomResumeConfig]):
    # The Common Room website tracking script loads from this host.
    codebase_detection = detect(script_hosts=("cdn.cr-relay.com",))

    lists_tables_without_credentials = True  # Static endpoint catalog, safe for public docs.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api.commonroom.io/docs/api-v2.html"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.commonroom.io": INVALID_TOKEN_MESSAGE,
            # Common Room answers a token that is not valid, or was deleted, with a 403.
            "403 Client Error: Forbidden for url: https://api.commonroom.io": INVALID_TOKEN_MESSAGE,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.common_room.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CommonRoomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Recent activities are read again on each sync, so append would add a second row for them.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=INCREMENTAL_FIELDS.keys(),
            default_incremental_lookback_seconds=dict.fromkeys(
                INCREMENTAL_FIELDS, ACTIVITIES_LOOKBACK_DAYS * 24 * 60 * 60
            ),
        )

    def validate_credentials(
        self,
        config: CommonRoomSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Every Common Room token reads every endpoint, so one token check covers each table.
        return validate_common_room_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CommonRoomResumeConfig]:
        return ResumableSourceManager[CommonRoomResumeConfig](inputs, CommonRoomResumeConfig)

    def source_for_pipeline(
        self,
        config: CommonRoomSourceConfig,
        resumable_source_manager: ResumableSourceManager[CommonRoomResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return common_room_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CRM,
            label="Common Room",
            keywords=["commonroom", "common room signals"],
            caption=(
                "Sync your Common Room contacts, organizations, activities, website visits, segments and custom "
                "objects. A Common Room admin can create an API token under **Settings > API tokens**."
            ),
            iconPath="/static/warehouse-sources/common_room/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/common-room",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
