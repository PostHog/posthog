from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GooglePageSpeedInsightsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.google_pagespeed_insights import (
    google_pagespeed_insights_source,
    validate_credentials as validate_google_pagespeed_insights_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PAGESPEED_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GooglePageSpeedInsightsSource(SimpleSource[GooglePageSpeedInsightsSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to render
    # in public docs without credentials.
    lists_tables_without_credentials = True
    supported_versions = ("v5",)
    default_version = "v5"
    api_docs_url = "https://developers.google.com/speed/docs/insights/v5/get-started"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPAGESPEEDINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_PAGE_SPEED_INSIGHTS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Google PageSpeed Insights",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Google Cloud API key and the URLs you want to analyze to pull PageSpeed Insights (Lighthouse) scores into the PostHog Data warehouse.

Create an API key in the [Google Cloud console](https://console.cloud.google.com/apis/credentials) and enable the **PageSpeed Insights API** for your project. A key raises your quota to 25,000 queries/day (400 per 100 seconds); without one, requests are heavily throttled.

There is no list endpoint — every request runs a fresh, on-demand analysis of a single URL — so enter one URL per line (starting with `http://` or `https://`). For example:

```
https://posthog.com
https://posthog.com/docs
```

Each analysis is a full Lighthouse run and can take several seconds. Each URL is analyzed once per selected table (desktop / mobile) per sync. To accumulate a history of scores over time, pick the **append** sync method on the table.
""",
            iconPath="/static/services/google_pagespeed_insights.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-pagespeed-insights",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Google Cloud API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="urls",
                        label="URLs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="https://posthog.com\nhttps://posthog.com/docs",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_pagespeed_insights.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid key surfaces as a 400 (`API key not valid`) and a project without the API
            # enabled as a 403 (`PERMISSION_DENIED`), both via `raise_for_status()`. Retrying can never
            # satisfy a credential/enablement problem. Match the stable status text and base host (the
            # `key` query param is redacted before the message reaches here).
            "400 Client Error: Bad Request for url: https://pagespeedonline.googleapis.com": "Your API key is invalid, or the PageSpeed Insights API is not enabled for your Google Cloud project. Check the key and enable the API, then reconnect.",
            "403 Client Error: Forbidden for url: https://pagespeedonline.googleapis.com": "Your API key does not have access to the PageSpeed Insights API. Enable the API for your Google Cloud project and check any key restrictions, then reconnect.",
        }

    def get_schemas(
        self,
        config: GooglePageSpeedInsightsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # The API exposes no server-side change cursor (every request is a fresh analysis), so
                # nothing is truly incremental. Append is supported: each sync re-runs the analysis and
                # merge dedupes on `[requested_url, analysis_timestamp]`, accumulating a time series.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=PAGESPEED_ENDPOINTS[endpoint].should_sync_default,
                description=PAGESPEED_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GooglePageSpeedInsightsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_google_pagespeed_insights_credentials(config.api_key, config.urls)

    def source_for_pipeline(self, config: GooglePageSpeedInsightsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_pagespeed_insights_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            urls_raw=config.urls,
            logger=inputs.logger,
        )
