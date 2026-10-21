from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klarna import KlarnaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.klarna import (
    KlarnaResumeConfig,
    klarna_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.settings import (
    API_DOCS_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KlarnaSource(ResumableSource[KlarnaSourceConfig, KlarnaResumeConfig]):
    codebase_detection = detect(
        env=("^KLARNA_", "^(NEXT_PUBLIC|VITE|REACT_APP)_KLARNA_"),
        script_hosts=("js.klarna.com", "x.klarnacdn.net"),
        npm=(
            "react-native-klarna-inapp-sdk",
            "@klarna/react-native-klarna-network-core",
            "@klarna/react-native-klarna-network-payment",
            "@klarna/react-native-klarna-network-messaging",
        ),
        cocoapods=("KlarnaMobileSDK",),
        composer=("klarna/checkout", "klarna/kco_rest"),
        maven=("com.klarna.mobile:sdk", "com.klarna.mobile:sdk-basic"),
        pub=("klarna_mobile_sdk_flutter",),
        rubygems=("klarna-checkout",),
        swiftpm=("github.com/klarna/klarna-mobile-sdk-spm", "github.com/klarna/klarna-mobile-sdk-ios"),
    )

    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL
    supported_versions = ("v1",)
    default_version = "v1"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLARNA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Klarna rejected your credentials. Reactivate or replace the key in the Merchant Portal.",
            "403 Client Error": "Klarna denied access. Check that your credentials can read settlements in the selected region.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KlarnaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = ENDPOINTS[schema.name].primary_keys
        return schemas

    def validate_credentials(
        self,
        config: KlarnaSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.api_key:
            return False, "Enter your Klarna API key."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Klarna table: {schema_name}"
        try:
            probe_credentials(config, schema_name or "payouts", self.resolve_api_version(api_version))
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, self.get_non_retryable_errors()["401 Client Error"]
                if error.response.status_code == 403:
                    if schema_name is None:
                        return True, None
                    return False, self.get_non_retryable_errors()["403 Client Error"]
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KlarnaResumeConfig]:
        return ResumableSourceManager(inputs, KlarnaResumeConfig)

    def source_for_pipeline(
        self,
        config: KlarnaSourceConfig,
        resumable_source_manager: ResumableSourceManager[KlarnaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.should_use_incremental_field:
            raise ValueError("Klarna tables support full refresh only. Select full refresh in the sync settings.")
        return klarna_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KLARNA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Klarna",
            iconPath="/static/services/klarna.png",
            docsUrl="https://posthog.com/docs/cdp/sources/klarna",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Import payouts and settlement transactions from Klarna. "
                "Create an API key in the Klarna Merchant Portal. "
                "Select the region and environment for your merchant account. "
                "The key needs read access to the Settlements API."
            ),
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
                        name="username",
                        label="Username (optional)",
                        caption="For HTTP Basic authentication, enter the UUID supplied with your API key.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        defaultValue="eu",
                        required=True,
                        options=[
                            SourceFieldSelectConfigOption(label="Europe", value="eu"),
                            SourceFieldSelectConfigOption(label="North America", value="na"),
                            SourceFieldSelectConfigOption(label="Oceania", value="oc"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        defaultValue="live",
                        required=True,
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Playground", value="playground"),
                        ],
                    ),
                ],
            ),
        )
