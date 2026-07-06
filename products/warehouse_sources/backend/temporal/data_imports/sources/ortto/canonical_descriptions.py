"""Canonical, documentation-sourced descriptions for Ortto endpoints and columns.

Sourced from the official Ortto API reference (https://help.ortto.com/developer/latest/api-reference/).
Keyed by the endpoint names in `settings.py` `ORTTO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Ortto table. Ortto exposes people and accounts as
field-id collections (built-in IDs like `str::email`, plus runtime-discovered `cm:*` custom
fields), so column coverage focuses on the documented built-in fields. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "people": {
        "description": "A person (contact) in Ortto's customer data platform, with profile and activity fields.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/person/",
        "columns": {
            "id": "Unique identifier for the person.",
            "str::first": "Person's first name.",
            "str::last": "Person's last name.",
            "str::email": "Person's email address.",
            "str::postal": "Person's postal/ZIP code.",
            "str::ei": "Person's external (customer) identifier.",
            "phn::phone": "Person's phone number.",
            "geo::city": "Person's city, derived from geolocation.",
            "geo::region": "Person's region/state, derived from geolocation.",
            "geo::country": "Person's country, derived from geolocation.",
            "bol::gdpr": "Whether the person is subject to GDPR.",
            "bol::p": "Whether the person is subscribed (permission to contact).",
            "bol::sp": "Whether the person is subscribed to SMS.",
            "dtz::b": "Person's date of birth.",
            "u4s::t": "Person's tags.",
            "idt::o": "IDs of the accounts (organizations) the person is associated with.",
        },
    },
    "accounts": {
        "description": "An account (organization/company) record in Ortto that people can be associated with.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/accounts/",
        "columns": {
            "id": "Unique identifier for the account.",
            "str:o:name": "Account (organization) name.",
            "str:o:website": "Account's website URL.",
            "str:o:industry": "Industry the account operates in.",
            "int:o:employees": "Number of employees at the account.",
        },
    },
    "audiences": {
        "description": "A saved audience (segment) of people defined by filter conditions in Ortto.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/audiences/",
        "columns": {
            "id": "Unique identifier for the audience.",
            "name": "The audience's name.",
        },
    },
    "tags": {
        "description": "A tag that can be applied to people in Ortto to label and segment them.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/tags/",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
        },
    },
    "person_custom_fields": {
        "description": "Definitions of the custom fields available on person records in Ortto.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/person/",
        "columns": {
            "id": "Field identifier (e.g. str:cm:my-field) used to reference the custom field.",
            "name": "Human-readable name of the custom field.",
            "type": "Data type of the custom field (e.g. text, number, boolean, date).",
        },
    },
    "account_custom_fields": {
        "description": "Definitions of the custom fields available on account records in Ortto.",
        "docs_url": "https://help.ortto.com/developer/latest/api-reference/accounts/",
        "columns": {
            "id": "Field identifier (e.g. str:o:my-field) used to reference the custom field.",
            "name": "Human-readable name of the custom field.",
            "type": "Data type of the custom field (e.g. text, number, boolean, date).",
        },
    },
}
