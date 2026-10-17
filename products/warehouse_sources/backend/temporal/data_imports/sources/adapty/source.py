from datetime import UTC, date, datetime
from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.adapty import (
    AdaptyResumeConfig,
    adapty_source,
    validate_credentials as validate_adapty_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adapty.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adapty import AdaptySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AdaptySource(ResumableSource[AdaptySourceConfig, AdaptyResumeConfig]):
    codebase_detection = detect(
        env=("^ADAPTY_", "^EXPO_PUBLIC_ADAPTY_"),
        npm=("react-native-adapty", "@adapty/capacitor", "@adapty/core", "adapty", "@adapty/react-native-ui"),
        cocoapods=("Adapty", "AdaptyUI"),
        maven=(
            "io.adapty:android-sdk",
            "io.adapty:android-ui",
            "io.adapty:android-ui-video",
            "io.adapty:adapty-kmp",
            "io.adapty:adapty-kmp-ui",
        ),
        pub=("adapty_flutter", "adapty_ui_flutter"),
        swiftpm=("github.com/adaptyteam/adaptysdk-ios",),
    )

    lists_tables_without_credentials = True
    api_docs_url = "https://adapty.io/docs/api-export-analytics"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADAPTY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ADAPTY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Adapty",
            caption="Import daily reports and paywalls for one Adapty app. Reports use UTC and exclude the current day.",
            docsUrl="https://posthog.com/docs/cdp/sources/adapty",
            iconPath="/static/services/adapty.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="secret_live_...",
                        caption="Get the app's secret key from Adapty Dashboard > App settings > API keys.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder="YYYY-MM-DD",
                        caption="All reports refresh from this date. Earlier dates need more API requests.",
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AdaptySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Adapty rejected the API key. Replace the app's secret API key and reconnect.",
            "403 Client Error: Forbidden": "Adapty denied access. Check the app's API permissions and reconnect.",
        }

    def validate_credentials(
        self, config: AdaptySourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            start = date.fromisoformat(config.start_date)
            if start.isoformat() != config.start_date or start >= datetime.now(UTC).date():
                raise ValueError
        except ValueError:
            return False, "Enter a report start date before today, in YYYY-MM-DD format."
        if not config.api_key or not config.api_key.isascii() or any(char.isspace() for char in config.api_key):
            return False, "Enter the app's secret API key without spaces."
        return validate_adapty_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdaptyResumeConfig]:
        return ResumableSourceManager(inputs, AdaptyResumeConfig)

    def source_for_pipeline(
        self,
        config: AdaptySourceConfig,
        resumable_source_manager: ResumableSourceManager[AdaptyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return adapty_source(config, resumable_source_manager, inputs)
