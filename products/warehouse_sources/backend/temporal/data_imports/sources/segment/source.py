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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.segment import (
    SegmentSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment import (
    SegmentResumeConfig,
    segment_source,
    validate_credentials as validate_segment_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SEGMENT_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SegmentSource(ResumableSource[SegmentSourceConfig, SegmentResumeConfig]):
    codebase_detection = detect(
        env=("^SEGMENT_WRITE_KEY$", "^(NEXT_PUBLIC|VITE|REACT_APP)_SEGMENT_WRITE_KEY$", "^TYPEWRITER_TOKEN$"),
        script_hosts=("cdn.segment.com", "cdn.segment.io", "cdn.edgefn.segment.com"),
        npm=(
            "@segment/analytics-node",
            "analytics-node",
            "@segment/analytics-next",
            "@segment/analytics-react-native",
            "@segment/analytics.js-core",
            "analytics.js",
            "@segment/analytics.js-integration-segmentio",
            "@segment/analytics.js-video-plugins",
            "@segment/snippet",
            "@segment/analytics-consent-tools",
            "@segment/analytics-consent-wrapper-onetrust",
            "@segment/consent-manager",
            "@segment/analytics-signals",
            "@segment/analytics-react",
            "@segment/edge-sdk",
            "@segment/public-api-sdk-typescript",
            "@segment/sovran-react-native",
            "typewriter",
            "@segment/analytics-react-native-plugin-adjust",
            "@segment/analytics-react-native-plugin-advertising-id",
            "@segment/analytics-react-native-plugin-amplitude-session",
            "@segment/analytics-react-native-plugin-appsflyer",
            "@segment/analytics-react-native-plugin-branch",
            "@segment/analytics-react-native-plugin-braze",
            "@segment/analytics-react-native-plugin-braze-middleware",
            "@segment/analytics-react-native-plugin-clevertap",
            "@segment/analytics-react-native-plugin-destination-filters",
            "@segment/analytics-react-native-plugin-device-token",
            "@segment/analytics-react-native-plugin-engage",
            "@segment/analytics-react-native-plugin-facebook-app-events",
            "@segment/analytics-react-native-plugin-firebase",
            "@segment/analytics-react-native-plugin-idfa",
            "@segment/analytics-react-native-plugin-kepler",
            "@segment/analytics-react-native-plugin-mixpanel",
            "@segment/analytics-react-native-plugin-onetrust",
            "@segment/analytics-react-native-adjust",
            "@segment/analytics-react-native-amplitude",
            "@segment/analytics-react-native-appboy",
            "@segment/analytics-react-native-appsflyer",
            "@segment/analytics-react-native-clevertap",
            "@segment/analytics-react-native-firebase",
            "@segment/analytics-react-native-google-analytics",
            "@segment/analytics-react-native-intercom",
            "@segment/analytics-react-native-mixpanel",
            "@analytics/segment",
            "ngx-segment-analytics",
            "vue-segment-analytics",
            "gatsby-plugin-segment-js",
            "analytics-react-native",
        ),
        pypi=("segment-analytics-python", "analytics-python"),
        cargo=("segment", "analytics"),
        cocoapods=(
            "Analytics",
            "Segment-Amplitude",
            "Segment-Firebase",
            "Segment-Adjust",
            "Segment-Mixpanel",
            "Segment-Intercom",
            "Segment-Bugsnag",
            "Segment-Flurry",
            "Segment-Localytics",
            "Segment-Taplytics",
            "Segment-ComScore",
            "Segment-Quantcast",
            "Segment-Optimizely",
            "Segment-GoogleAnalytics",
            "Segment-Countly",
            "Segment-Crittercism",
            "Segment-Facebook-App-Events",
            "Segment-Adobe-Analytics",
            "Segment-Nielsen-DCR",
            "Segment-Nielsen-DTVR",
            "Segment-Optimizely-X",
        ),
        composer=(
            "segmentio/analytics-php",
            "alt-three/segment",
            "binarcode/laravel-segment",
            "slashequip/laravel-segment",
        ),
        go=(
            "github.com/segmentio/analytics-go",
            "gopkg.in/segmentio/analytics-go.v3",
            "github.com/segmentio/public-api-sdk-go",
            "github.com/segmentio/objects-go",
        ),
        hex=("segment",),
        maven=(
            "com.segment.analytics.kotlin:android",
            "com.segment.analytics.android:analytics",
            "com.segment.analytics.java:analytics",
            "com.segment.analytics.kotlin:core",
            "com.segment.analytics.kotlin:consent",
            "com.segment.analytics.kotlin:destination-filters",
            "com.segment.analytics.kotlin:analytics-kotlin-live",
            "com.segment.analytics.kotlin:edge-functions",
            "com.segment.analytics.kotlin.consent:consent-onetrust",
            "com.segment.analytics.kotlin.signals:core",
            "com.segment.analytics.kotlin.signals:signals-kotlin",
            "com.segment.analytics.kotlin.signals:compose",
            "com.segment.analytics.kotlin.signals:navigation",
            "com.segment.analytics.kotlin.signals:navigation-gradle-plugin",
            "com.segment.analytics.kotlin.signals:okhttp3",
            "com.segment.analytics.kotlin.signals:java-net",
            "com.segment.analytics.kotlin.signals:uitoolkit",
            "com.segment.analytics.kotlin.signals:uitoolkit-gradle-plugin",
            "com.segment.analytics.kotlin.destinations:adjust",
            "com.segment.analytics.kotlin.destinations:adobe-analytics",
            "com.segment.analytics.kotlin.destinations:amplitude",
            "com.segment.analytics.kotlin.destinations:analytics-kotlin-engage",
            "com.segment.analytics.kotlin.destinations:appsflyer",
            "com.segment.analytics.kotlin.destinations:braze",
            "com.segment.analytics.kotlin.destinations:bugsnag",
            "com.segment.analytics.kotlin.destinations:comscore",
            "com.segment.analytics.kotlin.destinations:consent",
            "com.segment.analytics.kotlin.destinations:consent-onetrust",
            "com.segment.analytics.kotlin.destinations:engage",
            "com.segment.analytics.kotlin.destinations:facebookappevents",
            "com.segment.analytics.kotlin.destinations:firebase",
            "com.segment.analytics.kotlin.destinations:flurry",
            "com.segment.analytics.kotlin.destinations:intercom",
            "com.segment.analytics.kotlin.destinations:localytics",
            "com.segment.analytics.kotlin.destinations:mixpanel",
            "com.segment.analytics.kotlin.destinations:nielsen-dcr",
            "com.segment.analytics.kotlin.destinations:nielsen-dtvr",
            "com.segment.analytics.kotlin.destinations:optimizely-full-stack",
            "com.segment.analytics.kotlin.destinations:quantcast",
            "com.segment.analytics.android:analytics-wear",
            "com.segment.analytics.android:analytics-core",
            "com.segment.analytics.android.middlewares:mcvid",
            "com.segment.analytics.android.integrations:adjust",
            "com.segment.analytics.android.integrations:adobe-analytics",
            "com.segment.analytics.android.integrations:amplitude",
            "com.segment.analytics.android.integrations:apptimize",
            "com.segment.analytics.android.integrations:bugsnag",
            "com.segment.analytics.android.integrations:comscore",
            "com.segment.analytics.android.integrations:countly",
            "com.segment.analytics.android.integrations:crittercism",
            "com.segment.analytics.android.integrations:firebase",
            "com.segment.analytics.android.integrations:flurry",
            "com.segment.analytics.android.integrations:google-analytics",
            "com.segment.analytics.android.integrations:intercom",
            "com.segment.analytics.android.integrations:kahuna",
            "com.segment.analytics.android.integrations:localytics",
            "com.segment.analytics.android.integrations:mixpanel",
            "com.segment.analytics.android.integrations:moengage",
            "com.segment.analytics.android.integrations:nielsen-dtvr",
            "com.segment.analytics.android.integrations:nielsendcr",
            "com.segment.analytics.android.integrations:optimizely",
            "com.segment.analytics.android.integrations:optimizelyx",
            "com.segment.analytics.android.integrations:quantcast",
            "com.segment.analytics.android.integrations:taplytics",
            "com.segment.analytics.android.integrations:tapstream",
            "com.segment.analytics.java:analytics-spring-boot-starter",
            "com.segment.analytics.java:analytics-cli",
            "com.segment.publicapi:segment-publicapi",
        ),
        pub=(
            "segment_analytics",
            "segment_analytics_plugin_adjust",
            "segment_analytics_plugin_advertising_id",
            "segment_analytics_plugin_amplitude",
            "segment_analytics_plugin_appsflyer",
            "segment_analytics_plugin_firebase",
            "segment_analytics_plugin_idfa",
            "flutter_segment",
        ),
        rubygems=("analytics-ruby", "segment", "simple_segment"),
        swiftpm=(
            "github.com/segmentio/analytics-swift",
            "github.com/segmentio/analytics-ios",
            "github.com/segment-integrations/analytics-swift-adjust",
            "github.com/segment-integrations/analytics-swift-adobe-analytics",
            "github.com/segment-integrations/analytics-swift-amplitude",
            "github.com/segment-integrations/analytics-swift-appsflyer",
            "github.com/segment-integrations/analytics-swift-bugsnag",
            "github.com/segment-integrations/analytics-swift-comscore",
            "github.com/segment-integrations/analytics-swift-consent",
            "github.com/segment-integrations/analytics-swift-consent-onetrust",
            "github.com/segment-integrations/analytics-swift-engage",
            "github.com/segment-integrations/analytics-swift-facebook-app-events",
            "github.com/segment-integrations/analytics-swift-filters",
            "github.com/segment-integrations/analytics-swift-firebase",
            "github.com/segment-integrations/analytics-swift-flurry",
            "github.com/segment-integrations/analytics-swift-intercom",
            "github.com/segment-integrations/analytics-swift-live",
            "github.com/segment-integrations/analytics-swift-localytics",
            "github.com/segment-integrations/analytics-swift-mixpanel",
            "github.com/segment-integrations/analytics-swift-nielsen-dcr",
            "github.com/segment-integrations/analytics-swift-nielsen-dtvr",
            "github.com/segment-integrations/analytics-swift-optimizely",
            "github.com/segment-integrations/analytics-swift-quantcast",
            "github.com/segmentio/public-api-sdk-swift",
        ),
        alternative_to=(ProductKey.PIPELINE_DESTINATIONS,),
    )

    api_docs_url = "https://docs.segmentapis.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEGMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEGMENT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Segment",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter a Twilio Segment workspace-scoped Public API token to pull your Segment workspace configuration into the PostHog Data warehouse.

Create a **Public API token** in your Segment workspace under **Settings → Access Management → Tokens**, and pick the region your workspace lives in.

This connects to the Segment **Public API** (workspace configuration, admin, and metadata) — not the event or Profile data plane.""",
            iconPath="/static/services/segment.png",
            docsUrl="https://posthog.com/docs/cdp/sources/segment",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.segmentapis.com)", value="api"),
                            SourceFieldSelectConfigOption(label="EU (eu1.api.segmentapis.com)", value="eu1"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Public API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or insufficiently-scoped Public API token surfaces as a requests
            # HTTPError when `_fetch` calls `raise_for_status()`. Retrying can never fix a credential
            # problem, so stop the sync. Segment returns 401 when the header is missing and 403 for a
            # token that's present but not authorized; match the stable status text only.
            "401 Client Error: Unauthorized for url": "Your Segment Public API token is missing or invalid. Create a new Public API token in your Segment workspace settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Segment Public API token is invalid, revoked, or missing the permissions needed to sync this data. Create a new token with the required access in your Segment workspace settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SegmentSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The Segment Public API exposes no server-side timestamp filter on these resources, so every
        # endpoint is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=SEGMENT_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: SegmentSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_segment_credentials(config.api_token, config.region):
            return True, None

        return False, "Invalid Segment Public API token, or wrong region selected for this token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SegmentResumeConfig]:
        return ResumableSourceManager[SegmentResumeConfig](inputs, SegmentResumeConfig)

    def source_for_pipeline(
        self,
        config: SegmentSourceConfig,
        resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return segment_source(
            api_token=config.api_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
