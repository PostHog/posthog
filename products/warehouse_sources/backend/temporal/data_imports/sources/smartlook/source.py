from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlook import (
    SmartlookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.smartlook import (
    SmartlookResumeConfig,
    smartlook_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartlookSource(ResumableSource[SmartlookSourceConfig, SmartlookResumeConfig]):
    codebase_detection = detect(
        env=("^SMARTLOOK_",),
        script_hosts=("web-sdk.smartlook.com",),
        npm=("smartlook-client",),
        cocoapods=(
            "Smartlook",
            "SmartlookAnalytics",
            "Segment-Smartlook",
            "SmartlookConsentSDK",
            "SmartlookCrashReports",
        ),
        pub=("smartlook",),
        swiftpm=("github.com/smartlook/analytics-swift-package", "github.com/smartlook/smartlookswiftpackage"),
    )

    lists_tables_without_credentials = True
    # Smartlook versions each endpoint separately. Visitor search uses v2; other resources use v1.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://integrations.smartlook.com/docs/api-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTLOOK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Smartlook rejected the API token. Create a new token in your project settings.",
            "403 Client Error": "Smartlook denied API access. Check the token, project region, and REST API access.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SmartlookSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            {},
            names,
            should_sync_default={"visitor_events": False},
        )
        for schema in schemas:
            schema.detected_primary_keys = list(ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self,
        config: SmartlookSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.api_token or not config.api_token.isascii() or any(c.isspace() for c in config.api_token):
            return False, "Enter a Smartlook API token without spaces or unsupported characters."
        if config.region not in ("eu", "us"):
            return False, "Select the EU or US region from your Smartlook project settings."
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartlookResumeConfig]:
        return ResumableSourceManager(inputs, SmartlookResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartlookSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartlookResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Smartlook table: {inputs.schema_name}")
        if inputs.should_use_incremental_field:
            raise ValueError("Smartlook tables support full refresh only. Select full refresh for this table.")
        return smartlook_source(config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTLOOK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Smartlook (Smartlook.com s.r.o. / Cisco)",
            docsUrl="https://posthog.com/docs/cdp/sources/smartlook",
            iconPath="/static/services/smartlook.png",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Import visitors, sessions, event definitions, funnels, and visitor events with full refresh. "
                "Smartlook limits API requests by plan. Large imports can require the REST API add-on. "
                "Visitor events require requests for each visitor and are disabled by default."
            ),
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
                        caption="Ask the project owner to create a token in Project settings > REST API.",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Project region",
                        required=True,
                        defaultValue="eu",
                        options=[
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                            SourceFieldSelectConfigOption(label="US", value="us"),
                        ],
                    ),
                ],
            ),
        )
