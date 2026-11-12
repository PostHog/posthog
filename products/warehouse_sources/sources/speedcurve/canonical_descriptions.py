from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "rum_export": {
        "description": (
            "Raw real user monitoring (RUM) beacons from SpeedCurve's daily RUM export, one row per main, user timing,"
            " interaction or custom data beacon. The team must turn on the RUM export API in its RUM settings,"
            " and files exist only from that point forwards."
        ),
        "docs_url": "https://support.speedcurve.com/reference/export-rum-data",
        "columns": {
            "export_date": "UTC day of the export file that holds the row.",
            "export_row": "Line number of the row in its daily export file.",
            "page_id": "Unique identifier of the page view. Use it to group all rows of one page view.",
            "session_id": "Unique identifier of the visitor session.",
            "epoch": "Time the beacon data was recorded, as a Unix timestamp in seconds.",
            "account_id": "SpeedCurve account (team) identifier.",
            "page_label": "Page label, or the document title when no label was set.",
            "hostname": "Hostname of the page URL.",
            "pathname": "Pathname of the page URL.",
            "beacon_type": "Type of the row: main, user_timing, interaction, custom_data or other.",
            "device_type": "Device type: mobile, tablet or desktop.",
            "browser_and_version": "Browser name and major version, for example Chrome 128.",
            "operating_system": "Device operating system.",
            "country": "ISO 3166 country code of the visitor.",
            "dom_element_count": "Number of DOM elements on the page. Greater than zero only on main rows.",
            "response_start": "Time to first byte, in milliseconds since navigation start.",
            "first_contentful_paint": "First Contentful Paint, in milliseconds since navigation start.",
            "largest_contentful_paint": "Largest Contentful Paint, in milliseconds since navigation start.",
            "cumulative_layout_shift": "Largest burst of layout shift scores over the life of the page.",
            "interaction_to_next_paint": "Interaction to Next Paint duration, in milliseconds.",
            "first_input_delay": "First Input Delay, in milliseconds.",
            "user_timing_name": "Name of the User Timing mark or measure.",
            "user_timing_start": "Time of the User Timing mark, in milliseconds since navigation start.",
            "custom_data": "Comma-delimited name|value pairs that the page set with LUX.addData().",
            "long_tasks": "Delimited summary of long JavaScript tasks on the page.",
        },
    },
}
