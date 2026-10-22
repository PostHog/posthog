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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statsig import (
    StatsigSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.settings import API_VERSION, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.statsig import (
    StatsigResumeConfig,
    probe_credentials,
    statsig_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StatsigSource(ResumableSource[StatsigSourceConfig, StatsigResumeConfig]):
    codebase_detection = detect(
        env=("^STATSIG_", "^NEXT_PUBLIC_STATSIG_CLIENT_KEY$", "^VITE_STATSIG_SDK_KEY$"),
        npm=(
            "statsig-js",
            "statsig-node",
            "@statsig/js-client",
            "@statsig/react-bindings",
            "@statsig/statsig-node-core",
            "@statsig/react-native-bindings",
            "@statsig/react-native-core",
            "@statsig/expo-bindings",
            "@statsig/angular-bindings",
            "@statsig/next",
            "@statsig/web-analytics",
            "@statsig/session-replay",
            "@statsig/js-local-overrides",
            "@statsig/js-user-persisted-storage",
            "@statsig/js-on-device-eval-client",
            "@statsig/on-device-eval-core",
            "@statsig/js-on-device-eval-adapter",
            "@statsig/react-bindings-on-device-eval",
            "@statsig/react-native-bindings-on-device-eval",
            "@statsig/expo-bindings-on-device-eval",
            "@statsig/serverless-client",
            "@statsig/vercel-edge",
            "@statsig/experimental-edge-client",
            "@statsig/sidecar",
            "@statsig/cli-session-replay-node",
            "@statsig/client-core",
            "@statsig/statsig-ai",
            "@statsig/statsig-ai-node",
            "@statsig/azure-ai",
            "@statsig/siggy",
            "@statsig/pulumi-statsig",
            "@statsig/on-device-evaluations",
            "@statsig/precomputed-evaluations",
            "@statsig/client-extensions",
            "@flags-sdk/statsig",
            "statsig-react",
            "statsig-react-native",
            "statsig-react-native-expo",
            "statsig-js-lite",
            "statsig-js-local-eval",
            "statsig-node-lite",
            "statsig-node-vercel",
            "statsig-node-redis",
            "statsig-node-cloudflare-kv",
            "statsig-node-fastly",
            "statsig-node-fastly-kv",
            "statsig-akamai-edge",
            "statsig-sidecar",
            "statsig-sidecar-v2-beta",
            "statsig-web-analytics",
            "statsig-landing-page-exp",
            "statsig-unleash-connector",
        ),
        pypi=("statsig", "statsig-python-core", "statsig-ai", "azureai-statsig", "pulumi-statsig"),
        cargo=("statsig-rust", "statsig", "sigstat", "sigstat-grpc"),
        cocoapods=("Statsig", "StatsigOnDeviceEvaluations", "StatsigInternalObjC"),
        composer=("statsig/statsigsdk", "statsig/statsig-php-core", "statsig/statsig-core-php"),
        go=(
            "github.com/statsig-io/go-sdk",
            "github.com/statsig-io/statsig-go-core",
            "github.com/statsig-io/statsig-server-core/statsig-go",
            "github.com/statsig-io/fastly-data-adapter-go",
            "github.com/statsig-io/pulumi-statsig/sdk",
        ),
        hex=("statsig_elixir", "statsig"),
        maven=(
            "com.statsig:serversdk",
            "com.statsig:android-sdk",
            "com.statsig:javacore",
            "com.github.statsig-io:android-sdk",
            "com.github.statsig-io:android-local-eval",
        ),
        pub=("statsig",),
        rubygems=("statsig",),
        swiftpm=(
            "github.com/statsig-io/statsig-kit",
            "github.com/statsig-io/swift-on-device-evaluations-sdk",
            "github.com/statsig-io/ios-sdk",
        ),
        alternative_to=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    )

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.statsig.com/console-api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STATSIG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STATSIG,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Statsig",
            caption="Enter a Console API key from [Statsig Project Settings](https://console.statsig.com/api_keys). "
            "The key needs read access to the tables you select. The users table contains project members.",
            docsUrl="https://posthog.com/docs/cdp/sources/statsig",
            iconPath="/static/services/statsig.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Console API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StatsigSourceConfig,
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
                detected_primary_keys=[endpoint.primary_key],
                description=CANONICAL_DESCRIPTIONS[name]["description"],
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: StatsigSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Statsig table is not supported. Select a table from the source configuration."
        endpoint = ENDPOINTS[schema_name or "gates"]
        try:
            probe_credentials(config.api_key, endpoint.path, self.resolve_api_version(api_version))
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 401:
                return False, "Statsig rejected your API key. Enter a valid Console API key and reconnect the source."
            if status == 403:
                if schema_name is None:
                    return True, None
                return False, "Your Console API key cannot read this table. Give the key read access in Statsig."
            raise
        return True, None

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Statsig rejected your API key. Enter a valid Console API key and reconnect the source.",
            "403 Client Error": "Your Console API key cannot read this table. Give the key read access in Statsig.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StatsigResumeConfig]:
        return ResumableSourceManager(inputs, StatsigResumeConfig)

    def source_for_pipeline(
        self,
        config: StatsigSourceConfig,
        resumable_source_manager: ResumableSourceManager[StatsigResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return statsig_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
