from typing import cast
from uuid import UUID

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onesignal import (
    OneSignalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.onesignal import (
    OneSignalResumeConfig,
    onesignal_source,
    validate_credentials as validate_onesignal_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.settings import ONESIGNAL_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneSignalSource(ResumableSource[OneSignalSourceConfig, OneSignalResumeConfig]):
    codebase_detection = detect(
        env=("^ONE_?SIGNAL_", "^(NEXT_PUBLIC|VITE|REACT_APP|EXPO_PUBLIC)_ONE_?SIGNAL_"),
        script_hosts=("cdn.onesignal.com",),
        npm=(
            "@onesignal/node-onesignal",
            "react-native-onesignal",
            "react-onesignal",
            "onesignal-expo-plugin",
            "onesignal-cordova-plugin",
            "onesignal-node",
            "@onesignal/capacitor-plugin",
            "@onesignal/onesignal-vue3",
            "onesignal-ngx",
            "onesignal-vue",
            "@awesome-cordova-plugins/onesignal",
        ),
        pypi=("onesignal-python-api", "onesignal-sdk"),
        cargo=("onesignal-rust-api",),
        cocoapods=("OneSignalXCFramework", "OneSignal"),
        composer=("berkayk/onesignal-laravel", "norkunas/onesignal-php-api", "onesignal/onesignal-php-api"),
        go=("github.com/onesignal/onesignal-go-api",),
        maven=("com.onesignal:OneSignal", "com.onesignal:onesignal-java-client"),
        pub=("onesignal_flutter",),
        rubygems=("onesignal", "onesignal-ruby"),
        swiftpm=("github.com/onesignal/onesignal-xcframework", "github.com/onesignal/onesignal-ios-sdk"),
        alternative_to=(ProductKey.WORKFLOWS,),
    )

    lists_tables_without_credentials = True
    api_docs_url = "https://documentation.onesignal.com/reference/rest-api-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONESIGNAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONESIGNAL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="OneSignal",
            caption=(
                "Enter your App ID and App API key from OneSignal Settings > Keys & IDs. "
                "Import message delivery totals and segment metadata. "
                "OneSignal retains API messages for 30 days. Journey messages are excluded."
            ),
            iconPath="/static/services/onesignal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/onesignal",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="Enter your OneSignal App ID",
                        required=True,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="App API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="Enter your OneSignal App API key",
                        required=True,
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "OneSignal rejected the App API key. Replace the key and reconnect the source.",
            "403 Client Error": "The App API key cannot read this data. Check its permissions and IP restrictions.",
            "400 Client Error": "OneSignal rejected the request. Check the App ID and its App API key.",
        }

    def get_schemas(
        self,
        config: OneSignalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=list(endpoint.incremental_fields),
                detected_primary_keys=list(endpoint.primary_keys),
                description=CANONICAL_DESCRIPTIONS[name]["description"],
            )
            for name, endpoint in ONESIGNAL_ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: OneSignalSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            UUID(config.app_id)
        except ValueError:
            return False, "Enter a valid OneSignal App ID from Settings > Keys & IDs."
        if (
            not config.api_key
            or not config.api_key.isascii()
            or any(character.isspace() for character in config.api_key)
        ):
            return False, "Enter the App API key without spaces or the Key prefix."
        if schema_name is not None and schema_name not in ONESIGNAL_ENDPOINTS:
            return False, "This OneSignal table is unavailable. Select a supported table."
        return validate_onesignal_credentials(config.api_key, config.app_id, schema_name or "notifications")

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OneSignalResumeConfig]:
        return ResumableSourceManager(inputs, OneSignalResumeConfig)

    def source_for_pipeline(
        self,
        config: OneSignalSourceConfig,
        resumable_source_manager: ResumableSourceManager[OneSignalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return onesignal_source(
            api_key=config.api_key,
            app_id=config.app_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
