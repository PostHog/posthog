"""Canonical, documentation-sourced descriptions for Adobe Analytics endpoints and columns.

Sourced from the official Adobe Analytics 2.0 API reference
(https://developer.adobe.com/analytics-apis/docs/2.0/). Keyed by the endpoint names in
`settings.py` `ADOBE_ANALYTICS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Adobe Analytics table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "report_suites": {
        "description": "A report suite: the container that Adobe Analytics collects and reports data into.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/reportsuites/",
        "columns": {
            "rsid": "Report suite id, the identifier used when querying reports.",
            "name": "Human-readable name of the report suite.",
            "collectionItemType": "Type of the collection item, always `reportsuite` for this table.",
            "currency": "Three-letter currency code the report suite reports revenue in.",
            "timezoneZoneinfo": "IANA time zone the report suite's calendar days are aligned to.",
            "parentRsid": "Report suite this one rolls up into, for virtual report suites.",
        },
    },
    "segments": {
        "description": "A saved segment: a reusable filter applied to report data.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/segments/",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "Name of the segment as shown in Adobe Analytics.",
            "description": "Description entered when the segment was saved.",
            "rsid": "Report suite the segment is defined against.",
            "owner": "Login and id of the user who owns the segment.",
            "definition": "Segment rule definition, returned when expanded.",
            "created": "Timestamp the segment was created.",
            "modified": "Timestamp the segment was last modified.",
        },
    },
    "calculated_metrics": {
        "description": "A calculated metric: a metric derived from other metrics, segments, and functions.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/calculatedmetrics/",
        "columns": {
            "id": "Unique identifier for the calculated metric, usable as a metric id in reports.",
            "name": "Name of the calculated metric.",
            "description": "Description entered when the calculated metric was saved.",
            "rsid": "Report suite the calculated metric is defined against.",
            "owner": "Login and id of the user who owns the calculated metric.",
            "polarity": "Whether a higher value is good or bad.",
            "type": "Value type of the metric, such as decimal, currency, or percent.",
            "created": "Timestamp the calculated metric was created.",
            "modified": "Timestamp the calculated metric was last modified.",
        },
    },
    "dimensions": {
        "description": "The dimension catalog for a report suite: every dimension available to break a report down by.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/dimensions/",
        "columns": {
            "id": "Dimension id, used as the `dimension` value in a report request (e.g. `variables/page`).",
            "rsid": "Report suite the dimension catalog was listed for.",
            "title": "Display name of the dimension.",
            "name": "Internal name of the dimension.",
            "category": "Grouping the dimension appears under in the Adobe Analytics UI.",
            "type": "Data type of the dimension's values.",
            "pathable": "Whether the dimension supports pathing reports.",
            "segmentable": "Whether the dimension can be used inside a segment.",
            "reportable": "Which report types the dimension can be used in.",
        },
    },
    "metrics": {
        "description": "The metric catalog for a report suite: every metric available to request in a report.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/metrics/",
        "columns": {
            "id": "Metric id, used in a report's metric container (e.g. `metrics/visits`).",
            "rsid": "Report suite the metric catalog was listed for.",
            "title": "Display name of the metric.",
            "name": "Internal name of the metric.",
            "category": "Grouping the metric appears under in the Adobe Analytics UI.",
            "type": "Value type of the metric, such as int, decimal, currency, or percent.",
            "polarity": "Whether a higher value is good or bad.",
            "precision": "Number of decimal places the metric is reported to.",
        },
    },
    "users": {
        "description": "An Adobe Analytics user in the login company, used to resolve component owner ids.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/apis/",
        "columns": {
            "loginId": "Unique identifier for the user, matching the `owner.id` of segments and calculated metrics.",
            "login": "Login name of the user.",
            "companyid": "Login company id the user belongs to.",
            "email": "Email address of the user.",
            "firstName": "First name of the user.",
            "lastName": "Last name of the user.",
            "fullName": "Full display name of the user.",
            "title": "Job title entered for the user.",
            "imsUserId": "Adobe Identity Management System id of the user.",
            "disabled": "Whether the user account is disabled.",
            "createDate": "Timestamp the user was created.",
            "lastAccess": "Timestamp the user last accessed Adobe Analytics.",
            "tempLoginEnd": "Timestamp a temporary login expires, if the user is temporary.",
        },
    },
    "annotations": {
        "description": "An annotation: a note pinned to a date range to explain changes in report data.",
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/annotations/",
        "columns": {
            "id": "Unique identifier for the annotation.",
            "name": "Name of the annotation.",
            "description": "The annotation's description.",
            "dateRange": "ISO 8601 date range the annotation covers, in the report suite's time zone.",
            "color": "Display color of the annotation, `STANDARD1` through `STANDARD9`.",
            "applyToAllReports": "Whether the annotation applies to all report suites.",
            "scope": "The metrics and filters the annotation is limited to.",
            "createdDate": "Timestamp the annotation was created.",
            "modifiedDate": "Timestamp the annotation was last modified.",
            "modifiedById": "Id of the user who last modified the annotation.",
            "tags": "Tags applied to the annotation.",
            "shares": "Shares applied to the annotation.",
            "approved": "Whether an admin approved the annotation.",
            "owner": "Id, name, and login of the user who created the annotation.",
            "companyId": "Login company id of the annotation.",
            "reportSuiteName": "Friendly name of the annotation's report suite.",
            "rsid": "Report suite id the annotation belongs to.",
        },
    },
    "report": {
        "description": (
            "Daily report rows from the Adobe Analytics reporting API: one row per report suite, day, "
            "and value of the configured dimension, with the configured metrics as columns."
        ),
        "docs_url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/endpoints/reports/",
        "columns": {
            "rsid": "Report suite the report was run against.",
            "date": "Calendar day (report suite time zone) the report window covers.",
            "dimension": "Dimension id the report was broken down by, e.g. `variables/daterangeday`.",
            "item_id": "Adobe's identifier for the dimension value in this report row.",
            "value": "The dimension value itself, e.g. the page name or the day.",
        },
    },
}
