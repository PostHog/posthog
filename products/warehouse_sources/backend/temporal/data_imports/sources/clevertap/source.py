from typing import cast

from requests import HTTPError

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.clevertap import (
    ClevertapResumeConfig,
    clevertap_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clevertap.settings import (
    AUTH_ERROR,
    CURSOR_ERROR,
    ENDPOINTS,
    EXPORT_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clevertap import (
    ClevertapSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClevertapSource(ResumableSource[ClevertapSourceConfig, ClevertapResumeConfig]):
    codebase_detection = detect(
        env=("^CLEVER_?TAP_", "^(NEXT_PUBLIC|VITE|REACT_APP|EXPO_PUBLIC)_CLEVER_?TAP_"),
        script_hosts=("d2r1yp2w7bby2u.cloudfront.net", "static.clevertap.com"),
        npm=(
            "clevertap-react-native",
            "clevertap-web-sdk",
            "@types/clevertap-web-sdk",
            "clevertap-cordova",
            "@awesome-cordova-plugins/clevertap",
            "@clevertap/clevertap-expo-plugin",
            "clevertap",
            "clevertap-react",
        ),
        cocoapods=(
            "CleverTap-iOS-SDK",
            "CTNotificationContent",
            "CTNotificationService",
            "CleverTap-Geofence-SDK",
            "CleverTapLocation",
        ),
        maven=(
            "com.clevertap.android:clevertap-android-sdk",
            "com.clevertap.android:push-templates",
            "com.clevertap.android:clevertap-hms-sdk",
            "com.clevertap.android:clevertap-geofence-sdk",
        ),
        pub=("clevertap_plugin",),
        swiftpm=("github.com/clevertap/clevertap-ios-sdk",),
        alternative_to=(ProductKey.WORKFLOWS,),
    )

    lists_tables_without_credentials = True
    api_docs_url = "https://developer.clevertap.com/docs/get-events-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEVERTAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLEVERTAP,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CleverTap",
            iconPath="/static/services/clevertap.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clevertap",
            caption=(
                "Sync one event and its user profiles from the start date through yesterday (UTC). "
                "Profiles include only users who performed this event. "
                "CleverTap excludes some notification events from event exports."
            ),
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="passcode",
                        label="Passcode",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        defaultValue="eu1",
                        required=True,
                        options=[
                            SourceFieldSelectConfigOption(label="Europe", value="eu1"),
                            SourceFieldSelectConfigOption(label="United States", value="us1"),
                            SourceFieldSelectConfigOption(label="India", value="in1"),
                            SourceFieldSelectConfigOption(label="Singapore", value="sg1"),
                            SourceFieldSelectConfigOption(label="Indonesia", value="aps3"),
                            SourceFieldSelectConfigOption(label="United Arab Emirates", value="mec1"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="event_name",
                        label="Event name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="App Launched",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (YYYY-MM-DD)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="2024-01-01",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClevertapSourceConfig,
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
            descriptions={name: definition.description for name, definition in ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: ClevertapSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            probe_credentials(config, team_id, schema_name or "profiles")
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 400:
                return False, EXPORT_ERROR
            raise
        except ValueError as error:
            if str(error) == PERMISSION_ERROR and schema_name is None:
                return True, None
            return False, str(error)
        return True, None

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            AUTH_ERROR: AUTH_ERROR,
            PERMISSION_ERROR: PERMISSION_ERROR,
            CURSOR_ERROR: CURSOR_ERROR,
            EXPORT_ERROR: EXPORT_ERROR,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClevertapResumeConfig]:
        return ResumableSourceManager(inputs, ClevertapResumeConfig)

    def source_for_pipeline(
        self,
        config: ClevertapSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClevertapResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clevertap_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)
