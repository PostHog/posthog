from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the public IP2WHOIS v2 API documentation. Contact sub-objects (registrant,
# admin, tech, billing) share the same shape, so their nested fields aren't enumerated here — the
# top-level object descriptions and docs_url cover them.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "whois": {
        "description": (
            "WHOIS registration record for a single domain, from the IP2WHOIS (IP2Location) lookup API. "
            "One row per configured domain."
        ),
        "docs_url": "https://www.ip2whois.com/developers-api",
        "columns": {
            "domain": "The domain name that was looked up (the primary key; stamped from the configured domain).",
            "domain_id": "Registry-assigned unique identifier for the domain.",
            "status": "Domain status codes reported by the registry (e.g. clientTransferProhibited).",
            "create_date": "Date the domain was first registered (ISO 8601).",
            "update_date": "Date the WHOIS record was last updated (ISO 8601).",
            "expire_date": "Date the domain registration expires (ISO 8601).",
            "domain_age": "Age of the domain in days since registration.",
            "whois_server": "WHOIS server that holds the record for this domain.",
            "registrar": "Registrar details object (iana_id, name, url).",
            "registrant": "Registrant contact object (name, organization, address, phone, fax, email).",
            "admin": "Administrative contact object, same shape as registrant.",
            "tech": "Technical contact object, same shape as registrant.",
            "billing": "Billing contact object, same shape as registrant.",
            "nameservers": "List of nameserver hostnames for the domain.",
        },
    },
}
