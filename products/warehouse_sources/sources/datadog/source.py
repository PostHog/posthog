from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DatadogResumeConfig,
    datadog_source,
    validate_credentials as validate_datadog_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    DATADOG_API_VERSION_V1,
    DATADOG_DEFAULT_VERSION,
    DATADOG_ENDPOINTS,
    DATADOG_SUPPORTED_VERSIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.datadog import (
    DatadogSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DatadogSource(ResumableSource[DatadogSourceConfig, DatadogResumeConfig]):
    codebase_detection = detect(
        env=(
            "^DATADOG_",
            "^DD_API_KEY$",
            "^DD_APP_KEY$",
            "^DD_SITE$",
            "^DD_ENV$",
            "^DD_SERVICE$",
            "^DD_VERSION$",
            "^DD_TAGS$",
            "^DD_AGENT_HOST$",
            "^DD_TRACE_AGENT_URL$",
            "^DD_TRACE_AGENT_PORT$",
            "^DD_DOGSTATSD_HOST$",
            "^DD_DOGSTATSD_PORT$",
            "^DD_DOGSTATSD_URL$",
            "^DD_TRACE_ENABLED$",
            "^DD_TRACE_SAMPLE_RATE$",
            "^DD_TRACE_SAMPLING_RULES$",
            "^DD_TRACE_PROPAGATION_STYLE$",
            "^DD_TRACE_OTEL_ENABLED$",
            "^DD_TRACE_DEBUG$",
            "^DD_LOG_LEVEL$",
            "^DD_LOGS_INJECTION$",
            "^DD_RUNTIME_METRICS_ENABLED$",
            "^DD_PROFILING_ENABLED$",
            "^DD_APPSEC_ENABLED$",
            "^DD_IAST_ENABLED$",
            "^DD_DATA_STREAMS_ENABLED$",
            "^DD_DBM_PROPAGATION_MODE$",
            "^DD_LLMOBS_ENABLED$",
            "^DD_LLMOBS_ML_APP$",
            "^DD_LLMOBS_AGENTLESS_ENABLED$",
            "^DD_LLMOBS_SAMPLE_RATE$",
            "^DD_CIVISIBILITY_AGENTLESS_ENABLED$",
            "^DD_TEST_SESSION_NAME$",
            "^DD_GIT_REPOSITORY_URL$",
            "^DD_GIT_COMMIT_SHA$",
            "^DD_API_KEY_SECRET_ARN$",
            "^DD_LAMBDA_HANDLER$",
            "^DD_SERVERLESS_APPSEC_ENABLED$",
            "^DD_CAPTURE_LAMBDA_PAYLOAD$",
            "^DD_SERVICE_MAPPING$",
            "^DD_HOSTNAME$",
            "^DD_DD_URL$",
            "^DD_URL$",
            "^DD_HOST$",
            "^DD_LOGS_ENABLED$",
            "^DD_APM_ENABLED$",
            "^DD_APM_NON_LOCAL_TRAFFIC$",
            "^DD_DOGSTATSD_NON_LOCAL_TRAFFIC$",
            "^DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL$",
            "^DD_PROCESS_AGENT_ENABLED$",
            "^DD_ENTITY_ID$",
            "^DD_CLIENT_API_KEY$",
            "^DD_CLIENT_APP_KEY$",
            "^DD_BEARER_TOKEN$",
            "^DD_CLIENT_TOKEN$",
            "^DD_APP_ID$",
            "^DD_RUM_APPLICATION_ID$",
            "^DD_RUM_CLIENT_TOKEN$",
            "^DD_BETA_COMMANDS_ENABLED$",
            "^NEXT_PUBLIC_DD_APPLICATION_ID$",
            "^NEXT_PUBLIC_DD_CLIENT_TOKEN$",
        ),
        script_hosts=("datadoghq-browser-agent.com", "www.datadoghq-browser-agent.com"),
        npm=(
            "@datadog/datadog-api-client",
            "dd-trace",
            "@datadog/browser-rum",
            "@datadog/browser-logs",
            "@datadog/mobile-react-native",
            "@datadog/browser-rum-slim",
            "@datadog/browser-core",
            "@datadog/browser-rum-core",
            "@datadog/browser-rum-react",
            "@datadog/browser-rum-vue",
            "@datadog/browser-rum-angular",
            "@datadog/browser-rum-nextjs",
            "@datadog/browser-rum-nuxt",
            "@datadog/browser-rum-shopify",
            "@datadog/browser-worker",
            "@datadog/browser-plugin-wasm",
            "@datadog/mobile-react-native-code-push",
            "@datadog/mobile-react-native-apollo-client",
            "@datadog/mobile-react-native-babel-plugin",
            "@datadog/mobile-react-native-navigation",
            "@datadog/mobile-react-native-openfeature",
            "@datadog/mobile-react-native-session-replay",
            "@datadog/mobile-react-native-webview",
            "@datadog/mobile-react-navigation",
            "expo-datadog",
            "@datadog/electron-sdk",
            "dd-trace-electron",
            "datadog-roku",
            "@datadog/datadog-ci",
            "@datadog/datadog-ci-base",
            "@datadog/datadog-ci-plugin-aas",
            "@datadog/datadog-ci-plugin-cloud-run",
            "@datadog/datadog-ci-plugin-container-app",
            "@datadog/datadog-ci-plugin-coverage",
            "@datadog/datadog-ci-plugin-deployment",
            "@datadog/datadog-ci-plugin-dora",
            "@datadog/datadog-ci-plugin-ecs-fargate",
            "@datadog/datadog-ci-plugin-gate",
            "@datadog/datadog-ci-plugin-junit",
            "@datadog/datadog-ci-plugin-lambda",
            "@datadog/datadog-ci-plugin-sarif",
            "@datadog/datadog-ci-plugin-sbom",
            "@datadog/datadog-ci-plugin-stepfunctions",
            "@datadog/datadog-ci-plugin-synthetics",
            "@datadog/datadog-ci-plugin-terraform",
            "@datadog/cli",
            "@datadog/openfeature-browser",
            "@datadog/openfeature-node-server",
            "@datadog/flagging-core",
            "@datadog/esbuild-plugin",
            "@datadog/rollup-plugin",
            "@datadog/rspack-plugin",
            "@datadog/vite-plugin",
            "@datadog/webpack-plugin",
            "dd-trace-api",
            "@datadog/serverless-compat",
            "datadog-lambda-js",
            "serverless-plugin-datadog",
            "datadog-cdk-constructs",
            "datadog-cdk-constructs-v2",
            "@datadog/datadog-eks-blueprints-addon",
            "@datadog/ssp-addon-datadog",
            "@datadog/vercel-next-builder",
            "connect-datadog",
            "datadog",
            "@datadog/ui-extensions-sdk",
            "@datadog/ui-extensions-react",
            "@datadog/ui-apps-sdk",
            "@datadog/apps",
            "@datadog/apps-cli",
            "@datadog/action-catalog",
            "@datadog/backstage-plugin-datadog-entity-sync-backend",
            "datadog-metrics",
            "@datadog/datadog-api-client-action-connection",
            "@datadog/datadog-api-client-actions-datastores",
            "@datadog/datadog-api-client-agentless-scanning",
            "@datadog/datadog-api-client-api-management",
            "@datadog/datadog-api-client-apm",
            "@datadog/datadog-api-client-apm-retention-filters",
            "@datadog/datadog-api-client-app-builder",
            "@datadog/datadog-api-client-application-security",
            "@datadog/datadog-api-client-audit",
            "@datadog/datadog-api-client-auth-n-mappings",
            "@datadog/datadog-api-client-authentication",
            "@datadog/datadog-api-client-aws-integration",
            "@datadog/datadog-api-client-aws-logs-integration",
            "@datadog/datadog-api-client-azure-integration",
            "@datadog/datadog-api-client-case-management",
            "@datadog/datadog-api-client-case-management-attribute",
            "@datadog/datadog-api-client-case-management-type",
            "@datadog/datadog-api-client-change-management",
            "@datadog/datadog-api-client-ci-visibility-pipelines",
            "@datadog/datadog-api-client-ci-visibility-tests",
            "@datadog/datadog-api-client-cloud-authentication",
            "@datadog/datadog-api-client-cloud-cost-management",
            "@datadog/datadog-api-client-cloud-network-monitoring",
            "@datadog/datadog-api-client-cloudflare-integration",
            "@datadog/datadog-api-client-code-coverage",
            "@datadog/datadog-api-client-confluent-cloud",
            "@datadog/datadog-api-client-container-images",
            "@datadog/datadog-api-client-containers",
            "@datadog/datadog-api-client-csm-agents",
            "@datadog/datadog-api-client-csm-coverage-analysis",
            "@datadog/datadog-api-client-csm-ownership",
            "@datadog/datadog-api-client-csm-threats",
            "@datadog/datadog-api-client-dashboard-lists",
            "@datadog/datadog-api-client-dashboards",
            "@datadog/datadog-api-client-data-deletion",
            "@datadog/datadog-api-client-datasets",
            "@datadog/datadog-api-client-ddsql",
            "@datadog/datadog-api-client-deployment-gates",
            "@datadog/datadog-api-client-domain-allowlist",
            "@datadog/datadog-api-client-dora-metrics",
            "@datadog/datadog-api-client-downtimes",
            "@datadog/datadog-api-client-entity-risk-scores",
            "@datadog/datadog-api-client-error-tracking",
            "@datadog/datadog-api-client-events",
            "@datadog/datadog-api-client-fastly-integration",
            "@datadog/datadog-api-client-feature-flags",
            "@datadog/datadog-api-client-fleet-automation",
            "@datadog/datadog-api-client-gcp-integration",
            "@datadog/datadog-api-client-google-chat-integration",
            "@datadog/datadog-api-client-governance-console",
            "@datadog/datadog-api-client-high-availability-multi-region",
            "@datadog/datadog-api-client-hosts",
            "@datadog/datadog-api-client-identity-providers",
            "@datadog/datadog-api-client-incident-services",
            "@datadog/datadog-api-client-incident-teams",
            "@datadog/datadog-api-client-incidents",
            "@datadog/datadog-api-client-integrations",
            "@datadog/datadog-api-client-ip-allowlist",
            "@datadog/datadog-api-client-ip-ranges",
            "@datadog/datadog-api-client-jira-integration",
            "@datadog/datadog-api-client-key-management",
            "@datadog/datadog-api-client-llm-observability",
            "@datadog/datadog-api-client-logs",
            "@datadog/datadog-api-client-logs-archives",
            "@datadog/datadog-api-client-logs-custom-destinations",
            "@datadog/datadog-api-client-logs-indexes",
            "@datadog/datadog-api-client-logs-metrics",
            "@datadog/datadog-api-client-logs-pipelines",
            "@datadog/datadog-api-client-logs-restriction-queries",
            "@datadog/datadog-api-client-metrics",
            "@datadog/datadog-api-client-microsoft-teams-integration",
            "@datadog/datadog-api-client-monitors",
            "@datadog/datadog-api-client-network-device-monitoring",
            "@datadog/datadog-api-client-notebooks",
            "@datadog/datadog-api-client-observability-pipelines",
            "@datadog/datadog-api-client-oci-integration",
            "@datadog/datadog-api-client-okta-integration",
            "@datadog/datadog-api-client-on-call",
            "@datadog/datadog-api-client-on-call-paging",
            "@datadog/datadog-api-client-opsgenie-integration",
            "@datadog/datadog-api-client-org-authorized-clients",
            "@datadog/datadog-api-client-org-connections",
            "@datadog/datadog-api-client-org-groups",
            "@datadog/datadog-api-client-organizations",
            "@datadog/datadog-api-client-pager-duty-integration",
            "@datadog/datadog-api-client-powerpack",
            "@datadog/datadog-api-client-processes",
            "@datadog/datadog-api-client-product-analytics",
            "@datadog/datadog-api-client-reference-tables",
            "@datadog/datadog-api-client-report-schedules",
            "@datadog/datadog-api-client-reporting-and-sharing",
            "@datadog/datadog-api-client-restriction-policies",
            "@datadog/datadog-api-client-roles",
            "@datadog/datadog-api-client-rum",
            "@datadog/datadog-api-client-rum-audience-management",
            "@datadog/datadog-api-client-rum-config",
            "@datadog/datadog-api-client-rum-metrics",
            "@datadog/datadog-api-client-rum-operations",
            "@datadog/datadog-api-client-rum-replay-heatmaps",
            "@datadog/datadog-api-client-rum-replay-playlists",
            "@datadog/datadog-api-client-rum-replay-sessions",
            "@datadog/datadog-api-client-rum-replay-viewership",
            "@datadog/datadog-api-client-rum-retention-filters",
            "@datadog/datadog-api-client-seats",
            "@datadog/datadog-api-client-security-monitoring",
            "@datadog/datadog-api-client-sensitive-data-scanner",
            "@datadog/datadog-api-client-service-accounts",
            "@datadog/datadog-api-client-service-checks",
            "@datadog/datadog-api-client-service-definition",
            "@datadog/datadog-api-client-service-level-objective-corrections",
            "@datadog/datadog-api-client-service-level-objectives",
            "@datadog/datadog-api-client-service-now-integration",
            "@datadog/datadog-api-client-service-scorecards",
            "@datadog/datadog-api-client-slack-integration",
            "@datadog/datadog-api-client-snapshots",
            "@datadog/datadog-api-client-software-catalog",
            "@datadog/datadog-api-client-spa",
            "@datadog/datadog-api-client-spans",
            "@datadog/datadog-api-client-spans-metrics",
            "@datadog/datadog-api-client-static-analysis",
            "@datadog/datadog-api-client-status-pages",
            "@datadog/datadog-api-client-synthetics",
            "@datadog/datadog-api-client-tag-policies",
            "@datadog/datadog-api-client-tags",
            "@datadog/datadog-api-client-team-connections",
            "@datadog/datadog-api-client-teams",
            "@datadog/datadog-api-client-test-optimization",
            "@datadog/datadog-api-client-usage-metering",
            "@datadog/datadog-api-client-users",
            "@datadog/datadog-api-client-webhooks-integration",
            "@datadog/datadog-api-client-widgets",
            "@datadog/datadog-api-client-workflow-automation",
        ),
        pypi=(
            "datadog",
            "datadog-api-client",
            "ddtrace",
            "datadog-lambda",
            "datadog-serverless-compat",
            "ddtrace-api",
            "ddtestpy",
            "datadog-checks-base",
            "datadog-cdk-constructs",
            "datadog-cdk-constructs-v2",
            "dogapi",
            "dogstatsd-python",
        ),
        cargo=(
            "datadog-api-client",
            "datadog-opentelemetry",
            "opentelemetry-datadog",
            "dogstatsd",
            "metrics-exporter-dogstatsd",
        ),
        cocoapods=(
            "DatadogCore",
            "DatadogRUM",
            "DatadogLogs",
            "DatadogTrace",
            "DatadogSessionReplay",
            "DatadogCrashReporting",
            "DatadogWebViewTracking",
            "DatadogFlags",
            "DatadogProfiling",
            "DatadogObjc",
            "DatadogSDK",
            "DatadogSDKObjc",
            "DatadogSDKCrashReporting",
            "DatadogSDKAlamofireExtension",
            "DatadogAlamofireExtension",
            "DatadogSDKTesting",
            "DatadogOpenFeatureProvider",
        ),
        composer=(
            "datadog/dd-trace",
            "datadog/php-datadogstatsd",
            "chaseconey/laravel-datadog-helper",
            "okvpn/datadog-symfony",
            "graze/dog-statsd",
        ),
        go=(
            "gopkg.in/DataDog/dd-trace-go.v1",
            "github.com/DataDog/dd-trace-go",
            "github.com/DataDog/datadog-go",
            "github.com/DataDog/datadog-api-client-go",
            "github.com/DataDog/datadog-lambda-go",
            "github.com/DataDog/orchestrion",
            "github.com/DataDog/datadog-serverless-compat-go/datadogserverlesscompat",
            "github.com/DataDog/datadog-cdk-constructs-go/ddcdkconstruct",
            "github.com/zorkian/go-datadog-api",
            "gopkg.in/zorkian/go-datadog-api.v2",
        ),
        hex=("spandex_datadog",),
        maven=(
            "com.datadoghq:dd-sdk-android-rum",
            "com.datadoghq:dd-sdk-android-logs",
            "com.datadoghq:dd-trace-api",
            "com.datadoghq:java-dogstatsd-client",
            "com.datadoghq:datadog-api-client",
            "com.datadoghq:dd-java-agent",
            "com.datadoghq:dd-trace-ot",
            "com.datadoghq:dd-openfeature",
            "com.datadoghq:datadog-lambda-java",
            "com.datadoghq:datadog-cdk-constructs",
            "com.datadoghq:dd-javac-plugin",
            "com.datadoghq:dd-sdk-android",
            "com.datadoghq:dd-sdk-android-core",
            "com.datadoghq:dd-sdk-android-trace",
            "com.datadoghq:dd-sdk-android-trace-api",
            "com.datadoghq:dd-sdk-android-trace-otel",
            "com.datadoghq:dd-sdk-android-trace-coroutines",
            "com.datadoghq:dd-sdk-android-rum-coroutines",
            "com.datadoghq:dd-sdk-android-rum-debug-widget",
            "com.datadoghq:dd-sdk-android-session-replay",
            "com.datadoghq:dd-sdk-android-session-replay-compose",
            "com.datadoghq:dd-sdk-android-session-replay-material",
            "com.datadoghq:dd-sdk-android-ndk",
            "com.datadoghq:dd-sdk-android-okhttp",
            "com.datadoghq:dd-sdk-android-okhttp-otel",
            "com.datadoghq:dd-sdk-android-cronet",
            "com.datadoghq:dd-sdk-android-compose",
            "com.datadoghq:dd-sdk-android-webview",
            "com.datadoghq:dd-sdk-android-timber",
            "com.datadoghq:dd-sdk-android-fresco",
            "com.datadoghq:dd-sdk-android-glide",
            "com.datadoghq:dd-sdk-android-coil",
            "com.datadoghq:dd-sdk-android-coil3",
            "com.datadoghq:dd-sdk-android-rx",
            "com.datadoghq:dd-sdk-android-sqldelight",
            "com.datadoghq:dd-sdk-android-tv",
            "com.datadoghq:dd-sdk-android-apollo",
            "com.datadoghq:dd-sdk-android-flags",
            "com.datadoghq:dd-sdk-android-flags-openfeature",
            "com.datadoghq:dd-sdk-android-profiling",
            "com.datadoghq:dd-sdk-android-ktx",
            "com.datadoghq:dd-sdk-android-gradle-plugin",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-core",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-rum",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-logs",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-session-replay",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-webview",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-ktor",
            "com.datadoghq:dd-sdk-kotlin-multiplatform-ktor3",
        ),
        pub=(
            "datadog_flutter_plugin",
            "datadog_tracking_http_client",
            "datadog_session_replay",
            "datadog_webview_tracking",
            "datadog_inappwebview_tracking",
            "datadog_gql_link",
            "datadog_grpc_interceptor",
            "datadog_dio",
            "datadog_flags",
            "datadog_flags_flutter",
        ),
        rubygems=(
            "dogapi",
            "datadog",
            "ddtrace",
            "datadog_api_client",
            "dogstatsd-ruby",
            "datadog-ci",
            "datadog-lambda",
            "chef-handler-datadog",
            "fluent-plugin-datadog",
            "logstash-output-datadog_logs",
            "fastlane-plugin-datadog",
            "opentelemetry-exporters-datadog",
        ),
        swiftpm=(
            "github.com/datadog/dd-sdk-ios",
            "github.com/datadog/dd-sdk-swift-testing",
            "github.com/datadog/dd-openfeature-provider-swift",
            "github.com/datadog/dd-sdk-ios-apollo-interceptor",
            "github.com/datadog/swift-dogstatsd",
        ),
        alternative_to=(ProductKey.LOGS, ProductKey.TRACING, ProductKey.ERROR_TRACKING),
    )

    api_docs_url = "https://docs.datadoghq.com/api/latest/"

    supported_versions = DATADOG_SUPPORTED_VERSIONS
    default_version = DATADOG_DEFAULT_VERSION
    # Datadog deprecates its v1 API per-endpoint with no wholesale sunset date, so no date is set.
    deprecated_versions = (VersionDeprecation(version=DATADOG_API_VERSION_V1),)

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATADOG

    @property
    def connection_host_fields(self) -> list[str]:
        # The API/application keys are sent to the host derived from `site`, so changing the site
        # must re-require the secrets rather than reusing them against a different host.
        return ["site"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DATADOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Datadog",
            releaseStatus=ReleaseStatus.GA,
            caption="""Connect your Datadog account to sync logs, events, monitors, dashboards, and more into the PostHog Data warehouse.

Create an API key and an application key in your [Datadog organization settings](https://app.datadoghq.com/organization-settings/api-keys). The application key should be granted read scopes for the data you want to sync, for example:
- `dashboards_read`
- `monitors_read`
- `incident_read`
- `slos_read`
- `synthetics_read`
- `user_access_read`
- `metrics_read`
- `teams_read`
- `usage_read` and `billing_read` (usage and cost tables)
- `error_tracking_read` (error tracking issues), `apm_read` (error spans), and `logs_read_data` (logs and error logs)
- `events_read` (monitor alerts)

Logs, audit logs, and events read access is governed by your Datadog account's data retention.

Error tracking issues, error spans, error logs, and monitor alerts are off by default. Turn them on to feed errors and alerts into the PostHog Self-driving inbox. Error spans and error logs only contain `status:error` records, and monitor alerts only contain firing alerts from the last 7 days.""",
            iconPath="/static/services/datadog.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/datadog",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="site",
                        label="Datadog site",
                        required=True,
                        defaultValue="datadoghq.com",
                        options=[
                            SourceFieldSelectConfigOption(label="US1 (datadoghq.com)", value="datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US3 (us3.datadoghq.com)", value="us3.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US5 (us5.datadoghq.com)", value="us5.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="EU1 (datadoghq.eu)", value="datadoghq.eu"),
                            SourceFieldSelectConfigOption(label="AP1 (ap1.datadoghq.com)", value="ap1.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US1-FED (ddog-gov.com)", value="ddog-gov.com"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Datadog API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="application_key",
                        label="Application key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Datadog application key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Datadog API key. Generate a valid key and reconnect.",
            "403 Client Error": "Your Datadog application key is missing the required read scopes for this data. Grant the scopes and reconnect.",
            "expands one Datadog request per": "This table needs one Datadog request per parent record, and your account has more than we sync. Deselect the table to keep your other Datadog tables syncing.",
            "410 Client Error: Gone": "The requested Datadog data has fallen outside your account's retention window, or its pagination cursor expired. Retry the sync to start a fresh query.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DatadogSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=DATADOG_ENDPOINTS[endpoint].supports_incremental,
                supports_append=DATADOG_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=DATADOG_ENDPOINTS[endpoint].should_sync_default,
                description=(
                    "Limited to your Datadog account's retention window on initial sync"
                    if endpoint in LIMITED_RETENTION_ENDPOINTS
                    else None
                ),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: DatadogSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_datadog_credentials(config.site, config.api_key, config.application_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DatadogResumeConfig]:
        return ResumableSourceManager[DatadogResumeConfig](inputs, DatadogResumeConfig)

    def source_for_pipeline(
        self,
        config: DatadogSourceConfig,
        resumable_source_manager: ResumableSourceManager[DatadogResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return datadog_source(
            site=config.site,
            api_key=config.api_key,
            app_key=config.application_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
