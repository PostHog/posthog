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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.newrelic import (
    NewRelicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.new_relic import (
    NewRelicResumeConfig,
    new_relic_source,
    validate_credentials as validate_new_relic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NEW_RELIC_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NewRelicSource(ResumableSource[NewRelicSourceConfig, NewRelicResumeConfig]):
    codebase_detection = detect(
        env=("^NEW_RELIC_", "^NEWRELIC_", "^NEXT_PUBLIC_NEW_RELIC_", "^NRIA_", "^NR_INSTALL_"),
        script_hosts=("js-agent.newrelic.com",),
        npm=(
            "newrelic",
            "@newrelic/browser-agent",
            "@newrelic/native-metrics",
            "@newrelic/apollo-server-plugin",
            "@newrelic/next",
            "@newrelic/koa",
            "@newrelic/superagent",
            "@newrelic/aws-sdk",
            "@newrelic/mysql",
            "@newrelic/winston-enricher",
            "@newrelic/pino-enricher",
            "@newrelic/telemetry-sdk",
            "@newrelic/publish-sourcemap",
            "@newrelic/browser-agent-core",
            "@newrelic/continuous-automated-testing",
            "@newrelic/openai-observability",
            "@newrelic/netlify-plugin",
            "gatsby-plugin-newrelic",
            "serverless-newrelic-lambda-layers",
            "newrelic-react-native-agent",
            "@newrelic/newrelic-capacitor-plugin",
            "@awesome-cordova-plugins/newrelic",
            "@newrelic/video-core",
            "@newrelic/video-html5",
            "@newrelic/video-videojs",
            "@newrelic/video-shaka",
            "@newrelic/video-dash",
            "@newrelic/video-hls",
            "@newrelic/video-bitmovin",
            "@newrelic/video-caf",
            "@types/newrelic",
        ),
        pypi=(
            "newrelic",
            "newrelic-telemetry-sdk",
            "newrelic-lambda",
            "newrelic-lambda-cli",
            "newrelic-airflow-plugin",
            "opencensus-ext-newrelic",
            "opentelemetry-ext-newrelic",
            "nr-openai-observability",
        ),
        cocoapods=("NewRelicAgent", "NewRelicVideoAgent", "NRAVPlayerTracker", "NRIMATracker", "NRTHEOplayerTracker"),
        composer=("newrelic/monolog-enricher", "ekino/newrelic-bundle", "intouch/newrelic", "intouch/laravel-newrelic"),
        go=(
            "github.com/newrelic/go-agent",
            "github.com/newrelic/newrelic-telemetry-sdk-go",
            "github.com/newrelic/csec-go-agent",
            "github.com/newrelic/newrelic-client-go",
            "github.com/newrelic/infra-integrations-sdk",
            "github.com/newrelic/opentelemetry-exporter-go",
            "github.com/newrelic/newrelic-opencensus-exporter-go",
        ),
        hex=("new_relic_agent",),
        maven=(
            "com.newrelic.agent.java:newrelic-api",
            "com.newrelic.agent.android:android-agent",
            "com.newrelic.agent.java:newrelic-agent",
            "com.newrelic.agent.java:newrelic-java",
            "com.newrelic.agent.java:newrelic-opentelemetry-agent-extension",
            "com.newrelic.agent.java:newrelic-scala-api_2.10",
            "com.newrelic.agent.java:newrelic-scala-api_2.11",
            "com.newrelic.agent.java:newrelic-scala-api_2.12",
            "com.newrelic.agent.java:newrelic-scala-api_2.13",
            "com.newrelic.agent.java:newrelic-scala-api_3",
            "com.newrelic.agent.java:newrelic-cats-effect3-api_2.12",
            "com.newrelic.agent.java:newrelic-cats-effect3-api_2.13",
            "com.newrelic.agent.java:newrelic-scala-cats-api_2.12",
            "com.newrelic.agent.java:newrelic-scala-cats-api_2.13",
            "com.newrelic.agent.java:newrelic-scala-monix-api_2.11",
            "com.newrelic.agent.java:newrelic-scala-monix-api_2.12",
            "com.newrelic.agent.java:newrelic-scala-monix-api_2.13",
            "com.newrelic.agent.java:newrelic-scala-zio-api_2.11",
            "com.newrelic.agent.java:newrelic-scala-zio-api_2.12",
            "com.newrelic.agent.java:newrelic-scala-zio-api_2.13",
            "com.newrelic.agent.java:newrelic-scala-zio2-api_2.12",
            "com.newrelic.agent.java:newrelic-scala-zio2-api_2.13",
            "com.newrelic.agent.android:agent-gradle-plugin",
            "com.newrelic.agent.android:agent-ndk",
            "com.newrelic.agent.android:agent-maven-plugin",
            "com.newrelic.agent.android:android-agent-static",
            "com.newrelic.agent.android:gradle",
            "com.newrelic.telemetry:telemetry",
            "com.newrelic.telemetry:telemetry-core",
            "com.newrelic.telemetry:telemetry-all",
            "com.newrelic.telemetry:telemetry-http-okhttp",
            "com.newrelic.telemetry:telemetry-http-java11",
            "com.newrelic.telemetry:micrometer-registry-new-relic",
            "com.newrelic.telemetry:dropwizard-metrics-newrelic",
            "com.newrelic.telemetry:kamon-newrelic-reporter_2.13",
            "com.newrelic.telemetry:opentelemetry-exporters-newrelic",
            "com.newrelic.telemetry:opentelemetry-exporters-newrelic-auto",
            "com.newrelic.telemetry:newrelic-opentelemetry-javaagent",
            "com.newrelic.logging:jul",
            "com.newrelic.logging:log4j1",
            "com.newrelic.logging:log4j2",
            "com.newrelic.logging:logback",
            "com.newrelic.logging:logback11",
            "com.newrelic.logging:logback13",
            "com.newrelic.logging:dropwizard",
            "com.newrelic.logging:dropwizard3",
            "com.newrelic.opentracing:java-aws-lambda",
            "com.newrelic.opentracing:newrelic-java-lambda",
        ),
        pub=("newrelic_mobile",),
        rubygems=(
            "newrelic_rpm",
            "newrelic-infinite_tracing",
            "newrelic_security",
            "newrelic-telemetry_sdk",
            "fluent-plugin-newrelic",
            "logstash-output-newrelic",
            "newrelic_plugin",
            "newrelic_api",
        ),
        swiftpm=(
            "github.com/newrelic/newrelic-ios-agent-spm",
            "github.com/newrelic/newrelic-ios-agent",
            "github.com/newrelic/video-agent-ios",
        ),
        alternative_to=(ProductKey.LOGS, ProductKey.TRACING),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEWRELIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEWRELIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["new relic", "apm", "observability"],
            label="New Relic",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your New Relic User API key and account ID to pull your New Relic data into the PostHog Data warehouse.

You can create a User API key on the [API keys page](https://one.newrelic.com/admin-portal/api-keys/home) of your New Relic account. Your account ID is shown in the URL when viewing your account, or under **Administration** → **Access management** → **Accounts**.

If your account is hosted in New Relic's EU data center, select the EU region.
""",
            iconPath="/static/services/new_relic.png",
            docsUrl="https://posthog.com/docs/cdp/sources/new-relic",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="User API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="NRAK-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="1234567",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="US",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="US"),
                            SourceFieldSelectConfigOption(label="EU", value="EU"),
                        ],
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored API key is sent to, and `account_id` selects which
        # New Relic account the key is used against. Retargeting either must re-require the secret
        # so a preserved key can't be pointed at a different endpoint or account without re-entry.
        return ["account_id", "region"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.new_relic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked User API key surfaces as a requests HTTPError from
        # `raise_for_status()`. Retrying can never fix a credential problem, so stop the
        # sync. Match the stable status text and base host (one entry per region), not the
        # per-request path.
        invalid_key = "Your New Relic API key is invalid or has been revoked. Create a new User API key in your New Relic account, then reconnect."
        missing_permissions = "Your New Relic API key does not have permission to read this data. Check the key's user permissions in New Relic, then reconnect."
        return {
            "401 Client Error: Unauthorized for url: https://api.newrelic.com": invalid_key,
            "401 Client Error: Unauthorized for url: https://api.eu.newrelic.com": invalid_key,
            "403 Client Error: Forbidden for url: https://api.newrelic.com": missing_permissions,
            "403 Client Error: Forbidden for url: https://api.eu.newrelic.com": missing_permissions,
            # NerdGraph reports an authorization failure inside its `errors` array on an HTTP 200
            # rather than a 401/403, so it never matches the status-based keys above.
            "New Relic GraphQL error: Access denied": missing_permissions,
        }

    def get_schemas(
        self,
        config: NewRelicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NEW_RELIC_ENDPOINTS[endpoint]
            # NRQL event rows are immutable and carry no unique identifier, so event tables
            # sync append-only; entity/config listings have no server-side updated-since
            # filter, so they are full refresh only.
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: NewRelicSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_new_relic_credentials(config.api_key, config.account_id, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NewRelicResumeConfig]:
        return ResumableSourceManager[NewRelicResumeConfig](inputs, NewRelicResumeConfig)

    def source_for_pipeline(
        self,
        config: NewRelicSourceConfig,
        resumable_source_manager: ResumableSourceManager[NewRelicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return new_relic_source(
            api_key=config.api_key,
            account_id=config.account_id,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
