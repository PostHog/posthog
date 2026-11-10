from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Descriptions sourced from the Short.io API docs (https://developers.short.io/reference/apidomainsget).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "domains": {
        "description": "A branded short-link domain configured in your Short.io account.",
        "docs_url": "https://developers.short.io/reference/apidomainsget",
        "columns": {
            "id": "The unique ID of the domain.",
            "hostname": "The domain's hostname (e.g. 'example.short.gy').",
            "unicodeHostname": "The Unicode (IDN) form of the hostname.",
            "state": "The domain's setup state (e.g. 'configured', 'not_configured').",
            "TeamId": "The ID of the team that owns the domain.",
            "provider": "The DNS/hosting provider backing the domain.",
            "setupType": "How the domain was set up (e.g. 'dns', 'subdomain').",
            "cloaking": "Whether link cloaking (iframe masking) is enabled for the domain.",
            "hasFavicon": "Whether a custom favicon is configured for the domain.",
            "httpsLinks": "Whether generated links use HTTPS.",
            "redirect404": "The URL that 404s on this domain redirect to.",
            "hideReferer": "Whether the HTTP referer is hidden on redirects.",
            "caseSensitive": "Whether link paths on this domain are case sensitive.",
            "exportEnabled": "Whether click-data export is enabled for the domain.",
            "createdAt": "When the domain was created.",
            "updatedAt": "When the domain was last modified.",
        },
    },
    "links": {
        "description": "A short link in a Short.io domain. Full refresh includes changes to existing links.",
        "docs_url": "https://developers.short.io/reference/get_api-links",
        "columns": {
            "idString": "The unique link ID used by the Short.io API.",
            "domain_id": "The domain ID. Joins to domains.id.",
            "originalURL": "The destination URL.",
            "shortURL": "The short URL.",
            "path": "The link path within its domain.",
            "createdAt": "When the link was created.",
            "updatedAt": "When the link was last updated.",
            "tags": "The tags assigned to the link.",
        },
    },
    "link_clicks": {
        "description": "The total click count for a link, within the account's available history.",
        "docs_url": "https://developers.short.io/reference/getdomaindomainidlink_clicks",
        "columns": {
            "domain_id": "The domain ID. Joins to domains.id.",
            "link_id": "The link ID returned by the statistics API.",
            "clicks": "The total number of clicks for the link.",
        },
    },
    "last_clicks": {
        "description": "A raw click in the account's available history. Full refresh preserves clicks without unique event IDs.",
        "docs_url": "https://developers.short.io/reference/postdomaindomainidlast_clicks",
        "columns": {
            "domain_id": "The domain ID. Joins to domains.id.",
            "dt": "The date and time of the click.",
            "path": "The link path within its domain.",
            "human": "Whether Short.io identifies the visitor as a human.",
            "country": "The visitor's country.",
            "browser": "The visitor's browser.",
            "ref": "The full referrer URL.",
        },
    },
    "link_by_interval": {
        "description": "A daily click count for a link in UTC, within the account's available history.",
        "docs_url": "https://developers.short.io/reference/postlinklinkidby_interval",
        "columns": {
            "domain_id": "The domain ID. Joins to domains.id.",
            "link_id": "The link ID. Joins to links.idString.",
            "x": "The start of the daily interval in UTC.",
            "y": "The number of clicks in the interval.",
        },
    },
}
