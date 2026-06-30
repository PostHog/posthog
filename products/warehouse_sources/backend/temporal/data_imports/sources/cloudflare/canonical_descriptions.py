"""Canonical, documentation-sourced descriptions for Cloudflare endpoints and columns.

Sourced from the official Cloudflare API reference (https://developers.cloudflare.com/api/). Keyed
by the endpoint names in `settings.py` `CLOUDFLARE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Cloudflare table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A Cloudflare account that the API token can access.",
        "docs_url": "https://developers.cloudflare.com/api/resources/accounts/",
        "columns": {
            "id": "Unique identifier for the account.",
            "name": "The account's name.",
            "type": "The account's type (e.g. standard, enterprise).",
            "created_on": "Time at which the account was created.",
            "settings": "Account-level settings object.",
        },
    },
    "zones": {
        "description": "A zone — a domain and its DNS/configuration managed in Cloudflare.",
        "docs_url": "https://developers.cloudflare.com/api/resources/zones/",
        "columns": {
            "id": "Unique identifier for the zone.",
            "name": "The zone's domain name (e.g. example.com).",
            "status": "The zone's status (e.g. active, pending, initializing).",
            "paused": "Whether Cloudflare is paused for the zone.",
            "type": "The zone's type (full or partial).",
            "account": "The account the zone belongs to.",
            "owner": "The zone's owner (user or organization).",
            "plan": "The zone's current Cloudflare rate plan.",
            "name_servers": "Cloudflare name servers assigned to the zone.",
            "created_on": "Time at which the zone was created.",
            "modified_on": "Time at which the zone was last modified.",
            "activated_on": "Time at which the zone was activated.",
        },
    },
    "dns_records": {
        "description": "A DNS record belonging to a zone (A, CNAME, MX, TXT, and so on).",
        "docs_url": "https://developers.cloudflare.com/api/resources/dns/subresources/records/",
        "columns": {
            "id": "Unique identifier for the DNS record.",
            "type": "The DNS record type (e.g. A, AAAA, CNAME, MX, TXT).",
            "name": "The DNS record name (hostname).",
            "content": "The DNS record's value (e.g. IP address or target hostname).",
            "data": "Structured record data for record types that use it (e.g. SRV, CAA, LOC).",
            "tags": "Custom tags applied to the DNS record.",
            "proxied": "Whether traffic for the record is proxied through Cloudflare.",
            "ttl": "Time to live of the record, in seconds (1 means automatic).",
            "priority": "Priority of the record, used for MX and SRV records.",
            "created_on": "Time at which the record was created.",
            "modified_on": "Time at which the record was last modified.",
            "_zone_id": "Identifier of the parent zone, injected during the fan-out sync.",
        },
    },
}
