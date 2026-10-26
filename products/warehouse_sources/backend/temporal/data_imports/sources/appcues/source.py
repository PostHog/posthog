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
from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.appcues import (
    appcues_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appcues import (
    AppcuesSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppcuesSource(SimpleSource[AppcuesSourceConfig]):
    codebase_detection = detect(
        env=("^APPCUES_", "^(NEXT_PUBLIC|VITE|REACT_APP)_APPCUES_"),
        script_hosts=("fast.appcues.com", "fast.eu.appcues.com"),
        npm=(
            "@appcues/web-sdk",
            "@appcues/react-native",
            "@appcues/capacitor",
            "@appcues/segment-react-native",
            "@appcues/expo-config",
            "appcues-loader",
        ),
        cocoapods=("Appcues",),
        maven=("com.appcues:appcues", "com.appcues:segment-appcues"),
        pub=("appcues_flutter",),
        swiftpm=("github.com/appcues/appcues-ios-sdk", "github.com/appcues/segment-appcues-ios"),
        alternative_to=(ProductKey.PRODUCT_TOURS, ProductKey.SURVEYS),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api.appcues.com/v2/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPCUES

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Appcues rejected your API key or secret. Create a new key and reconnect the source.",
            "403 Client Error": "Your Appcues API key cannot read this table. Give the key read access and reconnect the source.",
            "404 Client Error": "Appcues could not find your account or table. Check your account ID and region.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppcuesSourceConfig,
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
                description=endpoint.description,
                detected_primary_keys=list(endpoint.primary_keys),
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: AppcuesSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Appcues table is not supported. Select a listed table."
        try:
            probe_credentials(config, schema_name or "flows", self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, "Appcues rejected your API key or secret. Create a new key and reconnect the source."
            if status == 403:
                if schema_name is None:
                    return True, None
                return False, "Your Appcues API key cannot read this table. Give the key read access and try again."
            if status == 404:
                return False, "Appcues could not find your account or table. Check your account ID and region."
            raise
        return True, None

    def source_for_pipeline(self, config: AppcuesSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return appcues_source(config, inputs, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPCUES,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Appcues",
            caption="Create an API key in Appcues Studio under Settings > Integrations > API Keys. "
            "Give the key read access to the experiences you want to sync. "
            "Copy your account ID from the account settings. "
            "This source syncs experience settings, segments, and tags. Event data and user profiles are not included.",
            docsUrl="https://posthog.com/docs/cdp/sources/appcues",
            iconPath="/static/services/appcues.png",
            releaseStatus=ReleaseStatus.BETA,
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
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Account region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="United States (US)", value="us"),
                            SourceFieldSelectConfigOption(label="European Union (EU)", value="eu"),
                        ],
                    ),
                ],
            ),
        )
