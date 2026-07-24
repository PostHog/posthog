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
}
