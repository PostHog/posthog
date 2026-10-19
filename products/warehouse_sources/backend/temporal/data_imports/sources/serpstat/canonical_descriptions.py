from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.serpstat.settings import DOCS_BASE, ENDPOINTS

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects available to the Serpstat account.",
        "docs_url": DOCS_BASE + ENDPOINTS["projects"].docs_slug,
        "columns": {
            "project_id": "The project identifier.",
            "project_name": "The project name.",
            "domain": "The domain associated with the project.",
            "created_at": "The date and time when the project was created.",
            "group": "The project group.",
            "type": "The account's role in the project: owner or reader.",
        },
    },
    "project_keywords": {
        "description": "Keywords configured for the selected Rank Tracker project.",
        "docs_url": DOCS_BASE + ENDPOINTS["project_keywords"].docs_slug,
        "columns": {
            "project_id": "The configured project identifier.",
            "id": "The internal identifier for the project keyword.",
            "keyword_id": "The keyword identifier.",
            "value": "The keyword text.",
            "added": "The date and time when the keyword was added.",
            "tags": "Tag names associated with the keyword.",
            "urls": "Target URLs for rank checks in each region.",
            "region": "The tracking status for each project region.",
        },
    },
    "project_regions": {
        "description": "Search regions and their status for the selected Rank Tracker project.",
        "docs_url": DOCS_BASE + ENDPOINTS["project_regions"].docs_slug,
        "columns": {
            "project_id": "The configured project identifier.",
            "id": "The project region identifier.",
            "active": "Whether tracking is active for this region.",
            "serpType": "The search result type: organic or paid.",
            "deviceType": "The device type: desktop or mobile.",
            "searchEngine": "The search engine used for tracking.",
            "country": "The country used for search results.",
            "region": "The region used for search results.",
            "city": "The city used for search results.",
            "langCode": "The language code used for search results.",
        },
    },
    "project_tags": {
        "description": "Tags created in the selected Rank Tracker project.",
        "docs_url": DOCS_BASE + ENDPOINTS["project_tags"].docs_slug,
        "columns": {
            "project_id": "The configured project identifier.",
            "tag_uuid": "The unique tag identifier.",
            "tag": "The tag name.",
        },
    },
    "project_positions": {
        "description": "Keyword positions for the configured project region during the last seven days, grouped by keyword.",
        "docs_url": DOCS_BASE + ENDPOINTS["project_positions"].docs_slug,
        "columns": {
            "project_id": "The configured project identifier.",
            "keyword_id": "The keyword identifier.",
            "value": "The keyword text.",
            "added": "The date and time when the keyword was added.",
            "regions": "Position history, URLs, traffic estimates, and search volume for each returned region.",
            "tags": "Tag names associated with the keyword.",
        },
    },
}
