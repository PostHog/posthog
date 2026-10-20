from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.logrocket import (
    LogrocketSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.logrocket import (
    LogrocketResumeConfig,
    logrocket_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LogrocketSource(ResumableSource[LogrocketSourceConfig, LogrocketResumeConfig]):
    codebase_detection = detect(
        env=("^LOGROCKET_",),
        script_hosts=(
            "cdn.logrocket.io",
            "cdn.lr-ingest.io",
            "cdn.logr-in.com",
            "cdn.logrocket.com",
            "cdn.lr-in.com",
            "cdn.lr-in-prod.com",
            "cdn.lr-ingest.com",
            "cdn.ingest-lr.com",
            "cdn.lr-intake.com",
            "cdn.intake-lr.com",
            "cdn.logr-ingest.com",
            "cdn.lrkt-in.com",
            "cdn.lgrckt-in.com",
        ),
        npm=(
            "logrocket",
            "logrocket-react",
            "@logrocket/react-native",
            "logrocket-cli",
            "logrocket-ngrx",
            "logrocket-vuex",
            "logrocket-mobx",
            "logrocket-mobx-state-tree",
            "logrocket-fuzzy-search-sanitizer",
            "@logrocket/mcp-replay",
            "@logrocket/mcp",
        ),
        cocoapods=("LogRocket",),
        go=("github.com/LogRocket/logrocket-mcp-replay-go",),
        maven=("com.logrocket:logrocket", "com.logrocket:compose"),
        pub=("logrocket_flutter",),
        swiftpm=("github.com/logrocket/logrocket-ios-swift-package",),
        alternative_to=(ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING),
    )

    lists_tables_without_credentials = True
    api_docs_url = "https://docs.logrocket.com/docs/audit-log-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOGROCKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOGROCKET,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="LogRocket",
            iconPath="/static/services/logrocket.png",
            docsUrl="https://posthog.com/docs/cdp/sources/logrocket",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Create an API key in LogRocket under Settings > API Keys. "
                "Audit logging must be enabled by an admin on the Professional plan. "
                "Session events require the legacy Data Export add-on, which LogRocket has deprecated for SaaS. "
                "This source connects to api.logrocket.com."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        placeholder="example-org",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        caption="The organization ID in your LogRocket project URL.",
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        placeholder="example-project",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        caption="The project ID in your LogRocket project URL.",
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: LogrocketSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=False,
                incremental_fields=list(endpoint.incremental_fields),
                description=endpoint.description,
                detected_primary_keys=list(endpoint.primary_keys) if endpoint.primary_keys else None,
                should_sync_default=endpoint.should_sync_default,
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: LogrocketSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.logrocket.com": (
                "LogRocket rejected your API key. Create a new key in Settings > API Keys, then reconnect the source."
            ),
            "403 Client Error: Forbidden for url: https://api.logrocket.com": (
                "LogRocket denied access. Check the API key permissions and the required audit or export add-on."
            ),
        }

    def get_endpoint_permissions(
        self,
        config: LogrocketSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for name in endpoints:
            valid, error = self.validate_credentials(config, team_id, name, api_version)
            permissions[name] = None if valid else error
        return permissions

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LogrocketResumeConfig]:
        return ResumableSourceManager(inputs, LogrocketResumeConfig)

    def source_for_pipeline(
        self,
        config: LogrocketSourceConfig,
        resumable_source_manager: ResumableSourceManager[LogrocketResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return logrocket_source(config, resumable_source_manager, inputs)
