from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "site_audit_health_scores": {
        "description": "Site Audit health scores and totals for the selected project's latest completed crawl.",
        "docs_url": "https://docs.ahrefs.com/en/api/reference/site-audit/get-projects",
        "columns": {
            "project_id": "Identifier of the selected Site Audit project.",
            "project_name": "Name of the project.",
            "date": "Time when the last completed crawl finished, in GMT.",
            "health_score": "Proportion of internal URLs without errors in the last completed crawl.",
            "status": "Status of the most recent finished crawl.",
            "target_url": "Target URL for the project.",
            "target_mode": "Scope of the target: exact URL, prefix, domain, or subdomains.",
            "target_protocol": "Target protocol: HTTP, HTTPS, or both.",
            "total": "Total number of internal URLs crawled.",
            "urls_with_errors": "Number of internal URLs with errors.",
            "urls_with_warnings": "Number of internal URLs with warnings.",
            "urls_with_notices": "Number of internal URLs with notices.",
        },
    },
    "site_audit_issues": {
        "description": "Issue summaries and affected URL counts from the selected Site Audit project's latest crawl.",
        "docs_url": "https://docs.ahrefs.com/en/api/reference/site-audit/get-issues",
        "columns": {
            "project_id": "Identifier of the selected Site Audit project.",
            "issue_id": "Identifier of the issue type.",
            "name": "Name of the issue.",
            "category": "Site Audit category for the issue.",
            "importance": "Issue severity: Error, Warning, or Notice.",
            "crawled": "Number of URLs currently affected by the issue.",
            "is_indexable": "Whether the issue applies only to indexable pages.",
        },
    },
    "site_audit_pages": {
        "description": "A sample of up to 100 pages from the latest Site Audit crawl, ordered by URL.",
        "docs_url": "https://docs.ahrefs.com/en/api/reference/site-audit/get-page-explorer",
        "columns": {
            "project_id": "Identifier of the selected Site Audit project.",
            "url": "Address of the crawled page or resource.",
            "http_code": "HTTP status code returned by the URL.",
            "title": "Page titles found during the crawl.",
            "depth": "Minimum number of clicks from the crawl's starting page, including redirects.",
            "is_html": "Whether the resource has an HTML content type.",
        },
    },
}
