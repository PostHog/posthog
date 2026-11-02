from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "Sites configured for synthetic monitoring in the SpeedCurve team.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-sites-1",
        "columns": {
            "site_id": "Identifier of the monitored site.",
            "name": "Site name.",
            "checks_scheduled": "Number of scheduled checks.",
            "urls": "URLs monitored for the site.",
        },
    },
    "urls": {
        "description": "Monitored URLs across the team's sites, with metadata for their latest tests.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-urls",
        "columns": {
            "site_id": "Identifier of the parent site, copied from the response containing this URL.",
            "url_id": "Identifier of the monitored URL.",
            "url": "Address of the monitored page.",
            "label": "Label assigned to the page.",
            "latest_tests": "Latest test identifiers, timestamps, regions, and browsers for this URL.",
        },
    },
    "tests": {
        "description": "Synthetic tests, including queued, failed, and successful tests, with available performance metrics.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-tests",
        "columns": {
            "test_id": "Identifier of the synthetic test.",
            "site_id": "Identifier of the monitored site.",
            "url_id": "Identifier of the monitored URL.",
            "timestamp": "Test time as a Unix timestamp in seconds.",
            "status": "Test status: -2 means queued, -1 means failed, and 0 means successful.",
            "region": "Test location identifier.",
            "browser": "Browser used for the test.",
            "largest_contentful_paint": "Largest Contentful Paint metric for the test.",
            "cumulative_layout_shift": "Cumulative Layout Shift metric for the test.",
            "lighthouse_performance": "Lighthouse performance score for the test.",
        },
    },
    "deploys": {
        "description": "Deployments recorded in SpeedCurve, with their sites, timestamps, and notes.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-deploys",
        "columns": {
            "deploy_id": "Identifier of the deployment.",
            "site_id": "Identifier of the deployment's site.",
            "timestamp": "Deployment time as a Unix timestamp in seconds.",
            "note": "Short note for the deployment.",
            "detail": "Additional details for the deployment.",
        },
    },
    "notes": {
        "description": "Notes attached to the team's sites to explain changes in performance.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-notes",
        "columns": {
            "note_id": "Identifier of the note.",
            "site_id": "Identifier of the note's site.",
            "timestamp": "Note time as a Unix timestamp in seconds.",
            "note": "Short note text.",
            "detail": "Additional note details.",
        },
    },
    "budgets": {
        "description": "Synthetic performance budgets from dashboards visible to the entire team, with their evaluation data.",
        "docs_url": "https://support.speedcurve.com/reference/get-all-budgets",
        "columns": {
            "budget_id": "Identifier of the performance budget.",
            "metric": "Metric evaluated by the budget.",
            "absolute_threshold": "Absolute threshold for the metric.",
            "relative_threshold": "Relative threshold for the metric.",
            "created_at": "Budget creation time as a Unix timestamp in seconds.",
            "modified_at": "Last modification time as a Unix timestamp in seconds.",
            "status": "Result of the budget evaluation.",
            "notifications_enabled": "Whether the budget sends notifications.",
            "chart": "Chart configuration associated with the budget.",
        },
    },
}
