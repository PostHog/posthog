from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.superwall import (
    SuperwallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.settings import (
    BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.superwall.superwall import (
    SuperwallResumeConfig,
    probe_credentials,
    superwall_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SuperwallSource(ResumableSource[SuperwallSourceConfig, SuperwallResumeConfig]):
    codebase_detection = detect(
        env=("^SUPERWALL_", "^EXPO_PUBLIC_SUPERWALL_"),
        npm=(
            "expo-superwall",
            "@superwall/react-native-superwall",
            "@superwall/paywalls-js",
            "@superwall/paywalls-react",
            "@superwall/server",
            "@superwall/cli",
            "superwall",
            "superwall-api",
            "@capawesome/capacitor-superwall",
        ),
        cocoapods=("SuperwallKit",),
        maven=("com.superwall.sdk:superwall-android", "com.superwall.sdk:superwall-compose"),
        pub=("superwallkit_flutter",),
        swiftpm=("github.com/superwall/superwall-ios", "github.com/superwall-me/superwall-ios"),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://api.superwall.com/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUPERWALL

    def get_schemas(
        self,
        config: SuperwallSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = PRIMARY_KEYS[schema.name]
        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: SuperwallSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown Superwall table. Select a supported table."
        response = probe_credentials(config, schema_name, self.resolve_api_version(api_version))
        if response.status_code == 401:
            return False, "The Superwall API key is invalid or revoked. Create a new organization API key."
        if response.status_code == 403:
            if schema_name is None:
                return True, None
            return False, f"The Superwall API key needs the `{ENDPOINTS[schema_name].scope}` scope."
        if response.status_code == 404:
            return False, "Superwall could not find this resource. Check the project and application IDs."
        response.raise_for_status()
        return True, None

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {BASE_URL}": "The Superwall API key is invalid or revoked. Create a new organization API key.",
            f"403 Client Error: Forbidden for url: {BASE_URL}": "The Superwall API key lacks a required read scope. Check its permissions.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SuperwallResumeConfig]:
        return ResumableSourceManager(inputs, SuperwallResumeConfig)

    def source_for_pipeline(
        self,
        config: SuperwallSourceConfig,
        resumable_source_manager: ResumableSourceManager[SuperwallResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return superwall_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SUPERWALL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Superwall",
            caption=(
                "Create an organization API key in Superwall under Access Controls. "
                "Grant read scopes for the tables you select: `paywalls:read`, `campaigns:read`, "
                "`products:read`, `entitlements:read`, `surveys:read`, and `webhooks:read`. "
                "Webhook events include only the history retained by Superwall."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/superwall",
            iconPath="/static/services/superwall.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Organization API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="application_id",
                        label="Application ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
