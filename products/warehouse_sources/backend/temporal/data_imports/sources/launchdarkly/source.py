from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.launchdarkly import (
    LaunchDarklySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.launchdarkly import (
    LaunchDarklyResumeConfig,
    launchdarkly_source,
    validate_credentials as validate_launchdarkly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LAUNCHDARKLY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LaunchDarklySource(ResumableSource[LaunchDarklySourceConfig, LaunchDarklyResumeConfig]):
    codebase_detection = detect(
        env=(
            "^LAUNCHDARKLY_",
            "^LD_SDK_KEY$",
            "^LD_ENV_",
            "^LD_ACCESS_TOKEN$",
            "^LD_CLIENT_SIDE_ID",
            "^LD_CLIENTSIDE_ID$",
            "^LD_MOBILE_KEY",
            "^LD_PROJ_KEY",
            "^LD_REPO_NAME$",
            "^LD_BASE_URI$",
            "^LD_STREAM_URI$",
            "^LD_EVENTS_URI$",
            "^LD_SERVICE_NAME$",
            "^LD_OBSERVABILITY_BACKEND_URL$",
            "^NEXT_PUBLIC_LAUNCHDARKLY_",
            "^NEXT_PUBLIC_LD_SERVICE_NAME$",
            "^VITE_LD_CLIENT_SIDE_ID$",
            "^PUBLIC_LD_CLIENT_ID$",
            "^PUBLIC_LD_FLAG_KEY$",
        ),
        script_hosts=("app.launchdarkly.com",),
        npm=(
            "launchdarkly-node-server-sdk",
            "@launchdarkly/node-server-sdk",
            "launchdarkly-js-client-sdk",
            "launchdarkly-react-client-sdk",
            "@launchdarkly/js-client-sdk",
            "@launchdarkly/react-native-client-sdk",
            "@launchdarkly/vercel-server-sdk",
            "@launchdarkly/cloudflare-server-sdk",
            "@launchdarkly/react-sdk",
            "@launchdarkly/vue-client-sdk",
            "@launchdarkly/node-client-sdk",
            "@launchdarkly/browser",
            "@launchdarkly/browser-telemetry",
            "@launchdarkly/akamai-server-base-sdk",
            "@launchdarkly/akamai-server-edgekv-sdk",
            "@launchdarkly/fastly-server-sdk",
            "@launchdarkly/shopify-oxygen-sdk",
            "@launchdarkly/openfeature-node-server",
            "@launchdarkly/openfeature-cloudflare-server",
            "@launchdarkly/node-server-sdk-redis",
            "@launchdarkly/node-server-sdk-dynamodb",
            "@launchdarkly/node-server-sdk-otel",
            "@launchdarkly/server-sdk-ai",
            "@launchdarkly/server-sdk-ai-openai",
            "@launchdarkly/server-sdk-ai-langchain",
            "@launchdarkly/server-sdk-ai-vercel",
            "@launchdarkly/ai-server",
            "@launchdarkly/ai-node",
            "@launchdarkly/ai-otel",
            "@launchdarkly/ai-claude-agents",
            "@launchdarkly/ai-claude-messages",
            "@launchdarkly/ai-langchain-agents",
            "@launchdarkly/ai-langchain-messages",
            "@launchdarkly/ai-openai-agents",
            "@launchdarkly/ai-openai-messages",
            "@launchdarkly/ai-vercel-agents",
            "@launchdarkly/ai-vercel-messages",
            "@launchdarkly/observability",
            "@launchdarkly/observability-node",
            "@launchdarkly/observability-next",
            "@launchdarkly/observability-react-native",
            "@launchdarkly/o11y",
            "@launchdarkly/session-replay",
            "@launchdarkly/session-replay-react-native",
            "@launchdarkly/toolbar",
            "@launchdarkly/jest",
            "@launchdarkly/mcp-server",
            "@launchdarkly/ldcli",
            "launchdarkly-vue-client-sdk",
            "launchdarkly-node-client-sdk",
            "launchdarkly-electron-client-sdk",
            "launchdarkly-react-native-client-sdk",
            "launchdarkly-node-server-sdk-redis",
            "launchdarkly-node-server-sdk-dynamodb",
            "launchdarkly-node-server-sdk-consul",
            "launchdarkly-cloudflare-edge-sdk",
            "launchdarkly-remix-sdk",
            "launchdarkly-api",
            "launchdarkly-api-typescript",
            "jest-launchdarkly-mock",
            "ldclient-js",
            "ldclient-node",
            "ldclient-react",
            "@openfeature/launchdarkly-client-provider",
            "@flags-sdk/launchdarkly",
            "vitest-launchdarkly-mock",
            "cypress-ld-control",
            "ember-launch-darkly",
            "@flopflip/launchdarkly-adapter",
        ),
        pypi=(
            "launchdarkly-server-sdk",
            "ldclient-py",
            "launchdarkly-server-sdk-ai",
            "launchdarkly-server-sdk-ai-openai",
            "launchdarkly-server-sdk-ai-langchain",
            "launchdarkly-ai-python",
            "launchdarkly-ai-server",
            "launchdarkly-ai-claude-agents",
            "launchdarkly-ai-claude-messages",
            "launchdarkly-ai-langchain-agents",
            "launchdarkly-ai-langchain-messages",
            "launchdarkly-ai-openai-agents",
            "launchdarkly-ai-openai-messages",
            "launchdarkly-server-sdk-otel",
            "launchdarkly-openfeature-server",
            "launchdarkly-observability",
            "launchdarkly-api",
        ),
        cargo=("launchdarkly-server-sdk", "launchdarkly-server-sdk-redis"),
        cocoapods=("LaunchDarkly", "LaunchDarklyObservability", "LaunchDarklySessionReplay", "LaunchDarklyOtel"),
        composer=(
            "launchdarkly/server-sdk",
            "launchdarkly/launchdarkly-php",
            "launchdarkly/openfeature-server",
            "launchdarkly/server-sdk-consul",
            "launchdarkly/server-sdk-dynamodb",
            "launchdarkly/server-sdk-otel",
            "launchdarkly/server-sdk-redis-phpredis",
            "launchdarkly/server-sdk-redis-predis",
            "launchdarkly/api-client-php",
        ),
        go=(
            "github.com/launchdarkly/go-server-sdk",
            "github.com/launchdarkly/go-server-sdk/ldotel",
            "github.com/launchdarkly/go-server-sdk/ldai",
            "github.com/launchdarkly/go-server-sdk-ai",
            "github.com/launchdarkly/go-server-sdk-consul",
            "github.com/launchdarkly/go-server-sdk-dynamodb",
            "github.com/launchdarkly/go-server-sdk-firestore",
            "github.com/launchdarkly/go-server-sdk-redis-go-redis",
            "github.com/launchdarkly/go-server-sdk-redis-redigo",
            "github.com/launchdarkly/observability-sdk/go",
            "github.com/launchdarkly/api-client-go",
            "github.com/launchdarkly/ld-relay",
            "github.com/launchdarkly/go-client",
            "gopkg.in/launchdarkly/go-server-sdk.v4",
            "gopkg.in/launchdarkly/go-server-sdk.v5",
            "gopkg.in/launchdarkly/go-client.v4",
        ),
        hex=("launchdarkly_server_sdk", "eld"),
        maven=(
            "com.launchdarkly:launchdarkly-java-server-sdk",
            "com.launchdarkly:launchdarkly-android-client-sdk",
            "com.launchdarkly:launchdarkly-client",
            "com.launchdarkly:launchdarkly-android-client",
            "com.launchdarkly:launchdarkly-java-server-sdk-ai",
            "com.launchdarkly:launchdarkly-java-server-sdk-otel",
            "com.launchdarkly:launchdarkly-java-server-sdk-redis-store",
            "com.launchdarkly:launchdarkly-java-server-sdk-dynamodb-store",
            "com.launchdarkly:launchdarkly-java-server-sdk-consul-store",
            "com.launchdarkly:launchdarkly-client-dynamodb-store",
            "com.launchdarkly:launchdarkly-client-consul-store",
            "com.launchdarkly:launchdarkly-openfeature-serverprovider",
            "com.launchdarkly:launchdarkly-observability-android",
            "com.launchdarkly:api-client",
            "com.launchdarkly:api-client-java",
        ),
        pub=("launchdarkly_flutter_client_sdk", "launchdarkly_flutter_observability"),
        rubygems=(
            "launchdarkly-server-sdk",
            "ldclient-rb",
            "launchdarkly-server-sdk-ai",
            "launchdarkly-server-sdk-otel",
            "launchdarkly-openfeature-server-sdk",
            "launchdarkly-observability",
            "launchdarkly_api",
        ),
        swiftpm=("github.com/launchdarkly/ios-client-sdk", "github.com/launchdarkly/swift-launchdarkly-observability"),
        alternative_to=(ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS),
    )

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://apidocs.launchdarkly.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAUNCHDARKLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LAUNCHDARKLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["feature flags"],
            label="LaunchDarkly",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your LaunchDarkly access token to pull your projects, environments, feature flags, flag statuses, segments, experiments, holdouts, metrics, metric groups, members, teams, code references, and audit log into the PostHog Data warehouse.

You can create a personal or service access token in your [LaunchDarkly account settings](https://app.launchdarkly.com/settings/authorization). A token with the **Reader** role grants read access to every resource this source syncs.""",
            iconPath="/static/services/launchdarkly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/launchdarkly",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="api-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your LaunchDarkly access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your LaunchDarkly access token does not have permission for this resource. Please check the token's role and try again.",
        }

    def get_schemas(
        self,
        config: LaunchDarklySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # LaunchDarkly's API exposes no server-side timestamp filter on these resources,
        # so every endpoint is full-refresh only (no incremental/append support).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: LaunchDarklySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Fan-out endpoints can't be probed without a parent key, so confirm scope against their
        # parent list (/projects or /teams); top-level endpoints probe their own path.
        probe_path = "/caller-identity"
        if schema_name is not None:
            endpoint = LAUNCHDARKLY_ENDPOINTS.get(schema_name)
            if endpoint is not None:
                if endpoint.requires_team:
                    probe_path = "/teams"
                elif endpoint.requires_project or endpoint.requires_environment:
                    probe_path = "/projects"
                else:
                    probe_path = endpoint.path

        status = validate_launchdarkly_credentials(config.access_token, probe_path)

        if status is None:
            return False, "Could not reach LaunchDarkly. Please try again."
        if status == 401:
            return False, "Invalid LaunchDarkly access token"
        # A valid token may legitimately lack scope for a specific endpoint. Accept 403 at
        # source-create (schema_name is None); only reject it for a specific schema check.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Your access token does not have permission to read '{schema_name}'"
        if status >= 400:
            return False, f"LaunchDarkly returned an unexpected status ({status})"
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LaunchDarklyResumeConfig]:
        return ResumableSourceManager[LaunchDarklyResumeConfig](inputs, LaunchDarklyResumeConfig)

    def source_for_pipeline(
        self,
        config: LaunchDarklySourceConfig,
        resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return launchdarkly_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
