"""Canonical, documentation-sourced descriptions for DebugBear endpoints and columns.

Sourced from the official DebugBear API docs (https://www.debugbear.com/docs/api). Keyed by
the endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced DebugBear table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Projects": {
        "description": "A DebugBear project — a group of monitored pages that share alerting and reporting settings.",
        "docs_url": "https://www.debugbear.com/docs/projects-api",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "The project's display name.",
            "pages": "The monitored pages configured within this project (id, name, url, region, test schedule, and device settings), as returned by the DebugBear API.",
        },
    },
    "Pages": {
        "description": "A monitored page inside a DebugBear project — the URL, its test schedule, and the device it is tested on.",
        "docs_url": "https://www.debugbear.com/docs/lab-test-api",
        "columns": {
            "id": "Unique identifier for the monitored page. Matches `page_id` on PageMetrics rows.",
            "name": "The page's display name.",
            "url": "The URL that is tested.",
            "region": "Server location the page is tested from.",
            "testSchedules": "The schedules the page is tested on (id, name, days, and times), as returned by the DebugBear API.",
            "device": "The simulated device the page is tested on (name, form factor, CPU throttling, and network settings).",
            "advancedSettings": "Advanced test settings applied to the page, such as basic auth or custom headers.",
            "tags": "Tags assigned to the page.",
            "project_id": "Identifier of the DebugBear project the page belongs to.",
            "project_name": "Display name of the DebugBear project the page belongs to.",
        },
    },
    "PageMetrics": {
        "description": (
            "A single synthetic (Lighthouse-based) lab test result for a monitored page — "
            "performance/accessibility/SEO scores, Core Web Vitals, and page weight for one build."
        ),
        "docs_url": "https://www.debugbear.com/docs/lab-test-api",
        "columns": {
            "project_id": "Identifier of the DebugBear project the tested page belongs to.",
            "project_name": "Display name of the DebugBear project the tested page belongs to.",
            "page_id": "Identifier of the monitored page that was tested.",
            "page_name": "Display name of the monitored page that was tested.",
            "page_url": "URL of the monitored page that was tested.",
            "analysis_date": "Date and time the test (analysis) was run.",
            "performance_score": "Lighthouse performance score (0-1) for this test.",
            "accessibility_score": "Lighthouse accessibility score (0-1) for this test.",
            "bestPractices_score": "Lighthouse best-practices score (0-1) for this test.",
            "seo_score": "Lighthouse SEO score (0-1) for this test.",
            "pwa_score": "Lighthouse Progressive Web App score (0-1) for this test.",
            "performance_speedIndex": "Speed Index metric (ms) for this test.",
            "performance_interactive": "Time to Interactive metric (ms) for this test.",
            "performance_firstContentfulPaint": "First Contentful Paint metric (ms) for this test.",
            "performance_firstMeaningfulPaint": "First Meaningful Paint metric (ms) for this test.",
            "performance_largestContentfulPaint": "Largest Contentful Paint metric (ms) for this test.",
            "performance_totalBlockingTime": "Total Blocking Time metric (ms) for this test.",
            "pageWeight_total": "Total page weight in bytes for this test.",
            "crux_lcp_p75": "Chrome UX Report field-data Largest Contentful Paint, 75th percentile (ms).",
            "crux_cls_p75": "Chrome UX Report field-data Cumulative Layout Shift, 75th percentile.",
            "crux_fcp_p75": "Chrome UX Report field-data First Contentful Paint, 75th percentile (ms).",
            "crux_fid_p75": "Chrome UX Report field-data First Input Delay, 75th percentile (ms).",
        },
    },
    "RumMetrics": {
        "description": (
            "Real user monitoring aggregates for a project, one row per metric per day. Values are "
            "the 75th percentile by default and cover the page views recorded in that day."
        ),
        "docs_url": "https://www.debugbear.com/docs/rum-api",
        "columns": {
            "project_id": "Identifier of the DebugBear project the metric was aggregated for.",
            "project_name": "Display name of the DebugBear project the metric was aggregated for.",
            "metric": "The aggregated metric, for example lcp, cls, inp, fcp, or ttfb.",
            "date": "Start of the day the aggregate covers.",
            "value": "The aggregated metric value for the day.",
            "count": "Number of page views included in the aggregate.",
            "stat": "The statistic the value reports, for example p75.",
        },
    },
    "RumPageViews": {
        "description": "An individual real user page view, with the metric values, page, device, and location recorded for it.",
        "docs_url": "https://www.debugbear.com/docs/rum-api",
        "columns": {
            "id": "Identifier PostHog derives from the page view's contents, because DebugBear returns no identifier for a page view.",
            "project_id": "Identifier of the DebugBear project the page view was recorded for.",
            "project_name": "Display name of the DebugBear project the page view was recorded for.",
            "date": "Date and time the page view happened.",
            "origin": "Origin of the page that was viewed.",
            "domain": "Domain of the page that was viewed.",
            "path": "URL path of the page that was viewed.",
            "queryString": "Query string of the page that was viewed.",
            "pageTitle": "Title of the page that was viewed.",
            "country": "Country the page view came from.",
            "device": "Device type the page view came from, for example desktop or mobile.",
            "operatingSystem": "Operating system the page view came from.",
            "devicePixelRatio": "Device pixel ratio of the viewing device.",
            "windowWidth": "Browser window width in pixels.",
            "windowHeight": "Browser window height in pixels.",
            "ttfbValue": "Time to First Byte for this page view, in milliseconds.",
            "fcp": "First Contentful Paint for this page view, in milliseconds.",
            "lcpValue": "Largest Contentful Paint for this page view, in milliseconds.",
            "lcpSelector": "CSS selector of the Largest Contentful Paint element.",
            "lcpText": "Text content of the Largest Contentful Paint element.",
            "lcpUrl": "URL of the Largest Contentful Paint resource, when it is an image.",
            "clsScrollTop": "Scroll position when the largest layout shift happened.",
            "inpValue": "Interaction to Next Paint for this page view, in milliseconds.",
            "inpStartTime": "Time the measured interaction started, in milliseconds after page load.",
            "inpSelector": "CSS selector of the element the measured interaction targeted.",
            "inpText": "Text content of the element the measured interaction targeted.",
            "inpEventName": "Name of the event behind the measured interaction, for example click.",
        },
    },
    "Annotations": {
        "description": "A timeline annotation marking an event, such as a release or a configuration change, on a project's performance charts.",
        "docs_url": "https://www.debugbear.com/docs/timeline-annotation-api",
        "columns": {
            "id": "Unique identifier for the annotation.",
            "title": "Short title shown on the chart.",
            "description": "Longer description of the annotated event.",
            "pageFilter": "Filter limiting the annotation to specific pages, for example `pageId:1234`. Empty when it applies to every page.",
            "date": "Date and time the annotated event happened.",
            "project_id": "Identifier of the DebugBear project the annotation belongs to.",
            "project_name": "Display name of the DebugBear project the annotation belongs to.",
        },
    },
}
