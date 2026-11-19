from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    detect,
)
from products.warehouse_sources.sources.zoom._config import ZoomSourceConfig
from products.warehouse_sources.sources.zoom.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RECORDINGS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.sources.zoom.zoom import (
    ZoomResumeConfig,
    supports_resume,
    validate_credentials as validate_zoom_credentials,
    zoom_source,
)


@SourceRegistry.register
class ZoomSource(ResumableSource[ZoomSourceConfig, ZoomResumeConfig]):
    codebase_detection = detect(
        env=(
            "^ZOOM_ACCOUNT_ID$",
            "^ZOOM_CLIENT_ID$",
            "^ZOOM_CLIENT_SECRET$",
            "^ZOOM_MEETING_SDK_KEY$",
            "^ZOOM_MEETING_SDK_SECRET$",
            "^ZOOM_VIDEO_SDK_KEY$",
            "^ZOOM_VIDEO_SDK_SECRET$",
            "^ZOOM_SDK_KEY$",
            "^ZOOM_SDK_SECRET$",
            "^ZOOM_COBROWSE_SDK_SECRET$",
            "^ZOOM_WEBHOOK_SECRET_TOKEN$",
            "^ZOOM_VERIFICATION_TOKEN$",
            "^ZOOM_BOT_JID$",
            "^ZM_CLIENT_ID$",
            "^ZM_CLIENT_SECRET$",
            "^ZM_REDIRECT_URL$",
            "^ZM_RTMS_",
        ),
        script_hosts=(
            "source.zoom.us",
            "source.zoomgov.com",
            "appssdk.zoom.us",
            "us01ccistatic.zoom.us",
            "us01-zcb.zoom.us",
        ),
        npm=(
            "@zoom/rivet",
            "@zoom/meetingsdk",
            "@zoom/appssdk",
            "@zoom/videosdk",
            "@zoom/videosdk-ui-toolkit",
            "@zoom/videosdk-react",
            "@zoom/react-native-videosdk",
            "@zoom/meetingsdk-react-native",
            "@zoom/rtms",
            "@zoom/cobrowsesdk",
            "@zoom/probesdk",
            "@zoomus/websdk",
            "@zoomus/chatbot",
            "@zoomus/chatbot-cli",
            "react-native-zoom-us",
        ),
        pypi=("rtms", "zoomus"),
        cocoapods=("ZoomVideoSDK", "ZoomMeetingSDK"),
        maven=(
            "us.zoom.meetingsdk:zoomsdk",
            "us.zoom.uitoolkit:uitoolkit",
            "us.zoom.videosdk:zoomvideosdk-core",
            "us.zoom.videosdk:zoomvideosdk-annotation",
            "us.zoom.videosdk:zoomvideosdk-videoeffects",
            "us.zoom.videosdk:zoomvideosdk-whiteboard",
            "us.zoom.videosdk:zoomvideosdk-broadcast-streaming",
            "us.zoom.videosdk:ZoomVideoSDK",
            "us.zoom.videosdk-lite:zoomvideosdk-core",
            "us.zoom.videosdk-lite:zoomvideosdk-annotation",
            "us.zoom.videosdk-lite:zoomvideosdk-videoeffects",
        ),
        pub=("flutter_zoom_videosdk",),
        rubygems=("zoom_rb",),
    )

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.zoom.us/docs/api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOOM

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.zoom.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            OAUTH2_PERMANENT_ERROR_MARKER: "Zoom rejected the client ID or client secret. Check the account ID, client ID and client secret, then reconnect.",
            "401 Client Error": "Zoom authentication failed. Please check your account ID, client ID, and client secret.",
            "Invalid access token": "Zoom authentication failed. Please reconnect the source.",
            "403 Client Error": "Your Zoom app is missing the required scopes. Grant user/meeting/webinar read scopes and reconnect.",
            # Zoom returns this as a 400, not a 401/403, so it needs its own entry: the token itself
            # lacks a scope the endpoint requires.
            "api error: code=4711": "Your Zoom app is missing the required scopes. Grant user/meeting/webinar read scopes and reconnect.",
        }

    def get_schemas(
        self,
        config: ZoomSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the date-windowed report and recording endpoints have a server-side date filter;
        # the rest are full refresh.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                default_incremental_lookback_seconds=(
                    RECORDINGS_INCREMENTAL_LOOKBACK_SECONDS if endpoint == "recordings" else None
                ),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ZoomSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_zoom_credentials(
            account_id=config.account_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            schema_name=schema_name,
        )

    def resume_covers_run(self, *, incremental_or_append: bool, schema_name: str | None = None) -> bool:
        return schema_name is None or schema_name not in ENDPOINTS or supports_resume(schema_name)

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
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOOM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Zoom",
            releaseStatus=ReleaseStatus.GA,
            caption="""Sync your Zoom users, groups, meetings, webinars, registrants, attendance, usage reports, and cloud recordings into the PostHog Data warehouse.

Create a **Server-to-Server OAuth** app in the [Zoom App Marketplace](https://marketplace.zoom.us/develop/create) and copy its Account ID, Client ID, and Client Secret below.

Grant the following read scopes:
- `user:read:list_users:admin`
- `meeting:read:list_meetings:admin`
- `webinar:read:list_webinars:admin`
- `meeting:read:list_registrants:admin` and `webinar:read:list_registrants:admin` for registrants
- `meeting:read:list_past_instances:admin`, `meeting:read:list_past_participants:admin`, `webinar:read:list_past_instances:admin` and `webinar:read:list_past_participants:admin` for instances and participants
- `group:read:list_groups:admin` and `group:read:list_members:admin` for groups
- `report:read:list_users:admin` for the host usage report
- `cloud_recording:read:list_user_recordings:admin` for recordings
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
