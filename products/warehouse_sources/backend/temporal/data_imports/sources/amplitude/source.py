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
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.amplitude import (
    AMPLITUDE_INVALID_ARCHIVE_ERROR,
    AmplitudeResumeConfig,
    amplitude_source,
    validate_credentials as validate_amplitude_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.settings import (
    AMPLITUDE_ENDPOINTS,
    EVENTS_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amplitude import (
    AmplitudeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmplitudeSource(ResumableSource[AmplitudeSourceConfig, AmplitudeResumeConfig]):
    codebase_detection = detect(
        env=(
            "^AMPLITUDE_",
            "^NEXT_PUBLIC_AMPLITUDE_",
            "^VITE_AMPLITUDE_",
            "^VITE_PUBLIC_AMPLITUDE_",
            "^REACT_APP_AMPLITUDE_",
            "^PUBLIC_AMPLITUDE_",
            "^NUXT_PUBLIC_AMPLITUDE_",
            "^EXPO_PUBLIC_AMPLITUDE_",
            "^NG_APP_AMPLITUDE_",
            "^AMPLI_TOKEN$",
        ),
        script_hosts=("cdn.amplitude.com", "cdn.eu.amplitude.com", "d24n15hnbwhuhn.cloudfront.net"),
        npm=(
            "@amplitude/analytics-browser",
            "@amplitude/analytics-node",
            "@amplitude/analytics-react-native",
            "amplitude-js",
            "@amplitude/unified",
            "@amplitude/analytics-core",
            "@amplitude/analytics-types",
            "@amplitude/analytics-client-common",
            "@amplitude/marketing-analytics-browser",
            "@amplitude/unified-react-native",
            "@amplitude/node",
            "@amplitude/identify",
            "@amplitude/react-native",
            "@amplitude/plugin-autocapture-browser",
            "@amplitude/plugin-web-attribution-browser",
            "@amplitude/plugin-page-view-tracking-browser",
            "@amplitude/plugin-page-url-enrichment-browser",
            "@amplitude/plugin-custom-enrichment-browser",
            "@amplitude/plugin-event-property-attribution-browser",
            "@amplitude/plugin-user-agent-enrichment-browser",
            "@amplitude/plugin-network-capture-browser",
            "@amplitude/plugin-web-vitals-browser",
            "@amplitude/plugin-ga-events-forwarder-browser",
            "@amplitude/plugin-global-user-properties",
            "@amplitude/babel-plugin-autocapture-transformer",
            "@amplitude/session-replay-browser",
            "@amplitude/plugin-session-replay-browser",
            "@amplitude/session-replay-react-native",
            "@amplitude/plugin-session-replay-react-native",
            "@amplitude/segment-session-replay-plugin",
            "@amplitude/segment-session-replay-plugin-react-native",
            "@amplitude/experiment-js-client",
            "@amplitude/experiment-node-server",
            "@amplitude/experiment-react-native-client",
            "@amplitude/experiment-tag",
            "@amplitude/plugin-experiment-browser",
            "@amplitude/plugin-experiment-react-native",
            "@amplitude/skylab-js-client",
            "@amplitude/skylab-js-server",
            "@amplitude/engagement-browser",
            "@amplitude/plugin-engagement-react-native",
            "@amplitude/ai",
            "@amplitude/mcp-analytics",
            "@amplitude/ampli",
            "@amplitude/developer-cli",
            "@amplitude/wizard",
            "@amplitude/storybook-addon-amplitude",
        ),
        pypi=("amplitude-analytics", "amplitude-ai", "amplitude-experiment", "amplitude-mcp-analytics"),
        cocoapods=(
            "AmplitudeSwift",
            "Amplitude",
            "Amplitude-iOS",
            "AmplitudeUnified",
            "AmplitudeSessionReplay",
            "AmplitudeSwiftSessionReplayPlugin",
            "AmplitudeiOSSessionReplayMiddleware",
            "AmplitudeExperiment",
            "AmplitudeEngagementSwift",
        ),
        composer=("amplitude/experiment-php-server", "zumba/amplitude-php"),
        go=("github.com/amplitude/analytics-go", "github.com/amplitude/experiment-go-server"),
        maven=(
            "com.amplitude:analytics-android",
            "com.amplitude:android-sdk",
            "com.amplitude:java-sdk",
            "com.amplitude:analytics-core",
            "com.amplitude:unified-android",
            "com.amplitude:streaming-analytics-android",
            "com.amplitude:session-replay-android",
            "com.amplitude:plugin-session-replay-android",
            "com.amplitude:middleware-session-replay-android",
            "com.amplitude:plugin-segment-session-replay-android",
            "com.amplitude:experiment-android-client",
            "com.amplitude:experiment-jvm-server",
            "com.amplitude:amplitude-engagement-android",
        ),
        pub=("amplitude_flutter", "amplitude_session_replay", "amplitude_experiment", "amplitude_engagement_flutter"),
        rubygems=("amplitude-experiment", "amplitude-api"),
        swiftpm=(
            "github.com/amplitude/amplitude-swift",
            "github.com/amplitude/amplitude-ios",
            "github.com/amplitude/amplitudeunified-swift",
            "github.com/amplitude/amplitudesessionreplay-ios",
            "github.com/amplitude/amplitudestreaminganalytics-swift",
            "github.com/amplitude/experiment-ios-client",
            "github.com/amplitude/amplitude-engagement-swift",
        ),
        alternative_to=(ProductKey.PRODUCT_ANALYTICS,),
    )

    api_docs_url = "https://amplitude.com/docs/apis/analytics"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMPLITUDE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "Amplitude rejected the credentials. Generate a fresh API key and secret key in Amplitude "
            "(Settings → Organization settings → Projects) and reconnect."
        )
        return {
            "401 Client Error: Unauthorized": message,
            "403 Client Error: Forbidden": message,
            "Invalid API Key": message,
        }

    def get_retryable_errors(self) -> set[str]:
        # A corrupt export body is a transient download problem, not a configuration error —
        # Temporal retries the activity and re-downloads the same window from scratch.
        #
        # A requests.ReadTimeout/ConnectionError that survives `_get`'s own tenacity retry is a
        # transient network blip, not an Amplitude or customer problem — a large export window can
        # take long enough to exhaust the shared retry budget in a single try, leaving no time for
        # tenacity to retry in-process, but Temporal still retries the whole activity and resume
        # state re-fetches the same window. Mirrors GitHub's and Bitbucket's identical classification
        # of the same urllib3 wording.
        return {AMPLITUDE_INVALID_ARCHIVE_ERROR, "Read timed out"}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amplitude.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmplitudeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=endpoint.supports_incremental,
                supports_append=endpoint.supports_append,
                incremental_fields=endpoint.incremental_fields,
                description="Only syncs the last 30 days on initial sync" if endpoint.name == EVENTS_ENDPOINT else None,
            )
            for endpoint in AMPLITUDE_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: AmplitudeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_amplitude_credentials(config.api_key, config.secret_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AmplitudeResumeConfig]:
        return ResumableSourceManager[AmplitudeResumeConfig](inputs, AmplitudeResumeConfig)

    def source_for_pipeline(
        self,
        config: AmplitudeSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amplitude_source(
            api_key=config.api_key,
            secret_key=config.secret_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMPLITUDE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Amplitude",
            caption=(
                "Connect Amplitude with your project's **API key** and **secret key**, found in Amplitude under "
                "**Settings → Organization settings → Projects**. These authenticate the Export API (raw events), "
                "the Cohorts API, the Annotations API, and the Taxonomy API (event and property definitions).\n\n"
                "The events stream uses Amplitude's Export API, which enforces a ~2 hour data latency and only "
                "syncs the last 30 days on the initial sync."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/amplitude",
            iconPath="/static/services/amplitude.png",
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
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (amplitude.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (analytics.eu.amplitude.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
        )
