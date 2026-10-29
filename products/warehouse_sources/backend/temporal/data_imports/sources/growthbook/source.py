from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.growthbook import (
    GrowthBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.growthbook import (
    INVALID_URL,
    UNSAFE_HOST,
    GrowthBookResumeConfig,
    growthbook_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.settings import (
    DEFAULT_BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

INVALID_CREDENTIALS = "Your GrowthBook API key is invalid or expired. Update the key and reconnect."
MISSING_PERMISSIONS = "Your GrowthBook API key lacks read access to this table. Update its permissions and try again."


@SourceRegistry.register
class GrowthBookSource(ResumableSource[GrowthBookSourceConfig, GrowthBookResumeConfig]):
    codebase_detection = detect(
        env=(
            "^GROWTHBOOK_",
            "^NEXT_PUBLIC_GROWTHBOOK_",
            "^GB_MCP_",
            "^GB_API_KEY$",
            "^GB_API_URL$",
            "^GB_APP_URL$",
            "^GB_API_HOST$",
            "^GB_CLIENT_KEY$",
            "^GB_SDK_KEY$",
            "^GB_OAUTH_ISSUER$",
            "^GB_SKILLS_ENABLED$",
        ),
        script_hosts=("cdn.growthbook.io",),
        npm=(
            "@growthbook/growthbook",
            "@growthbook/growthbook-react",
            "growthbook",
            "@growthbook/edge-cloudflare",
            "@growthbook/edge-lambda",
            "@growthbook/edge-fastly",
            "@growthbook/edge-utils",
            "@growthbook/proxy",
            "@growthbook/proxy-eval",
            "@growthbook/mcp",
            "@growthbook/wizard",
            "@growthbook/dev",
            "@flags-sdk/growthbook",
            "@openfeature/growthbook-provider",
            "@openfeature/growthbook-client-provider",
            "growthbook-roku",
        ),
        pypi=("growthbook", "growthbook-openfeature-provider"),
        cargo=("growthbook-rust", "growthbook-rust-sdk"),
        cocoapods=("GrowthBook-IOS", "GrowthBook"),
        composer=("growthbook/growthbook",),
        go=("github.com/growthbook/growthbook-golang", "github.com/growthbook/growthbook-openfeature-provider-go"),
        hex=("growthbook",),
        maven=(
            "io.growthbook.sdk:GrowthBook",
            "io.growthbook.sdk:GrowthBook-jvm",
            "io.growthbook.sdk:NetworkDispatcherKtor",
            "io.growthbook.sdk:NetworkDispatcherKtor-jvm",
            "io.growthbook.sdk:NetworkDispatcherOkHttp",
            "io.growthbook.sdk:NetworkDispatcherOkHttp-jvm",
            "io.growthbook.sdk:GrowthBookKotlinxSerialization",
            "io.growthbook.sdk:GrowthBookKotlinxSerialization-jvm",
            "com.github.growthbook:growthbook-sdk-java",
            "com.github.growthbook.growthbook-sdk-java:lib",
            "com.github.growthbook.growthbook-sdk-java:growthbook-cache-caffeine",
            "com.github.growthbook.growthbook-sdk-java:growthbook-cache-jcache",
            "com.github.growthbook:growthbook-openfeature-provider-java",
        ),
        pub=("growthbook_sdk_flutter",),
        rubygems=("growthbook",),
        swiftpm=("github.com/growthbook/growthbook-swift",),
        alternative_to=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    )

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.growthbook.io/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GROWTHBOOK

    @property
    def connection_host_fields(self) -> list[str]:
        return ["base_url"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_CREDENTIALS,
            "403 Client Error": MISSING_PERMISSIONS,
            INVALID_URL: INVALID_URL,
            UNSAFE_HOST: UNSAFE_HOST,
        }

    def get_schemas(
        self,
        config: GrowthBookSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GrowthBookSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "Unknown GrowthBook table. Refresh the table list and try again."
        try:
            probe_credentials(config, team_id, schema_name or "features", self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, INVALID_CREDENTIALS
            if status == 403:
                return (True, None) if schema_name is None else (False, MISSING_PERMISSIONS)
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GrowthBookResumeConfig]:
        return ResumableSourceManager(inputs, GrowthBookResumeConfig)

    def source_for_pipeline(
        self,
        config: GrowthBookSourceConfig,
        resumable_source_manager: ResumableSourceManager[GrowthBookResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return growthbook_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GROWTHBOOK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="GrowthBook",
            docsUrl="https://posthog.com/docs/cdp/sources/growthbook",
            iconPath="/static/services/growthbook.png",
            keywords=["feature flags", "experiments", "ab testing", "growthbook"],
            releaseStatus=ReleaseStatus.BETA,
            caption="Connect with a readonly secret API key from Settings > API Keys, or a personal access token with read access to the selected tables.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        placeholder="secret_...",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API base URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        secret=False,
                        placeholder=DEFAULT_BASE_URL,
                        caption="For self-hosted GrowthBook, enter your public HTTPS API URL including /api.",
                    ),
                ],
            ),
        )
