from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "site_audit": {
        "description": "Summary of the latest Site Audit for the configured Semrush project.",
        "docs_url": API_DOCS_URL + "#get-information-about-campaign",
        "columns": {
            "project_id": "Project ID supplied in the source configuration.",
            "id": "Semrush project ID.",
            "url": "Project URL.",
            "name": "Project name.",
            "status": "Current audit status.",
            "errors": "Number of errors found during the latest audit.",
            "warnings": "Number of warnings found during the latest audit.",
            "notices": "Number of notices found during the latest audit.",
            "pages_crawled": "Number of pages crawled.",
            "last_audit": "Date of the latest audit.",
            "defects": "Detected issue IDs and their counts.",
        },
    },
    "site_audit_snapshots": {
        "description": "Completed audit IDs and completion dates for the configured Semrush project.",
        "docs_url": API_DOCS_URL + "#get-list-of-campaign-snapshots",
        "columns": {
            "project_id": "Project ID supplied in the source configuration.",
            "snapshot_id": "Audit snapshot ID.",
            "finish_date": "Audit completion time in Unix milliseconds.",
        },
    },
    "site_audit_issue_descriptions": {
        "description": "Issue descriptions for Site Audit reports.",
        "docs_url": API_DOCS_URL + "#get-text-descriptions-about-issues",
        "columns": {
            "project_id": "Project ID supplied in the source configuration.",
            "id": "Issue type ID.",
            "title": "Issue title.",
            "title_page": "Issue title for the page report.",
            "url_column": "Label for the affected URL column.",
            "info_column": "Label for the issue information column.",
        },
    },
}
