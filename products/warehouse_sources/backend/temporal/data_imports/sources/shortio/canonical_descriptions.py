from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
}
