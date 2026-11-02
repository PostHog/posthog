from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_EXPORT_DOCS = "https://docs.scarf.sh/data-export/"

_EVENT_COLUMNS = {
    "id": "Identifier of the event. Scarf exports are at-least-once, so the same id can arrive twice.",
    "type": "Kind of event, for example binary-download, manifest-fetch or pixel-fetch.",
    "package": "Package that was downloaded, for package events.",
    "pixel": "Tracking pixel that was viewed, for pixel events.",
    "version": "Package version that was downloaded.",
    "time": "When the event happened, in UTC.",
    "referer": "Page that was viewed, for pixel events.",
    "user_agent": "User agent of the client, which shows the install method, platform and client.",
    "platform": "Platform Scarf derived from the request.",
    "variables": "Custom variables set on the download.",
    "origin_id": "Identifier of the user, through a specific device, behind the event.",
    "origin_latitude": "Latitude of the location Scarf matched to the event.",
    "origin_longitude": "Longitude of the location Scarf matched to the event.",
    "origin_country": "Country of the location Scarf matched to the event.",
    "origin_city": "City of the location Scarf matched to the event.",
    "origin_state": "State of the location Scarf matched to the event.",
    "origin_postal": "Postal code of the location Scarf matched to the event.",
    "origin_connection_type": "Type of IP address, for example business, isp or hosting.",
    "origin_company": "Company Scarf matched to the event.",
    "origin_domain": "Web domain of the matched company.",
    "dnt": "Whether the request asked not to be tracked.",
    "confidence": "Probability that the company match is correct.",
    "endpoint_id": "Identifier of the public-facing device, stable across user agent changes.",
    "mtc_quota_exceeded": "Whether Scarf removed the company details because the monthly company quota ran out.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "packages": {
        "description": "Packages tracked through Scarf.",
        "docs_url": "https://api-docs.scarf.sh/v2.html",
        "columns": {
            "id": "Unique identifier of the package.",
            "name": "Package name.",
            "owner": "Scarf user or organization that owns the package.",
            "type": "Package type: docker, file, python, npm, hackage or repository-jvm.",
            "short_description": "Short description of the package.",
            "website": "Website of the package.",
            "created_at": "When the package was added to Scarf.",
            "updated_at": "When the package was last updated in Scarf.",
        },
    },
    "tracking_pixels": {
        "description": "Tracking pixels that count views of docs and web pages.",
        "docs_url": "https://api-docs.scarf.sh/v2.html",
        "columns": {
            "id": "Unique identifier of the tracking pixel.",
            "name": "Name of the tracking pixel.",
            "owner": "Scarf user or organization that owns the pixel.",
            "package": "Package the pixel belongs to, if any.",
            "created_at": "When the pixel was created.",
            "updated_at": "When the pixel was last updated.",
        },
    },
    "package_events": {
        "description": "Raw package download events.",
        "docs_url": _EXPORT_DOCS,
        "columns": _EVENT_COLUMNS,
    },
    "tracking_pixel_events": {
        "description": "Raw tracking pixel views.",
        "docs_url": _EXPORT_DOCS,
        "columns": _EVENT_COLUMNS,
    },
    "company_rollup": {
        "description": "Companies matched to package and pixel activity over the last month.",
        "docs_url": _EXPORT_DOCS,
        "columns": {
            "company_name": "Name of the company.",
            "company_domain": "Web domain of the company.",
            "funnel_stage": "Stage of the company's journey with your software.",
            "total_events": "Package and pixel events matched to the company.",
            "total_downloads": "Package events matched to the company.",
            "total_unique_downloads": "Unique package events matched to the company.",
            "total_views": "Pixel events matched to the company.",
            "first_seen": "Date of the earliest event matched to the company.",
            "last_seen": "Date of the latest event matched to the company.",
            "company_industry": "Industry of the company.",
            "company_size": "Approximate employee count of the company.",
            "company_country": "Country of the company.",
        },
    },
}
