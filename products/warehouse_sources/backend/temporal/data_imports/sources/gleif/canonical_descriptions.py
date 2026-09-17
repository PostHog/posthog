"""Canonical, documentation-sourced descriptions for GLEIF endpoints and columns.

Sourced from the official GLEIF API (https://www.gleif.org/en/lei-data/gleif-api) and verified
against live responses. Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced GLEIF table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "LeiRecords": {
        "description": (
            "A Legal Entity Identifier (LEI) record: the legal name, address, jurisdiction, "
            "status, and registration details of one legally distinct entity."
        ),
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "The 20-character Legal Entity Identifier (LEI) code, same as `lei`.",
            "lei": "The 20-character Legal Entity Identifier (LEI) code.",
            "entity": "The entity's legal name, addresses, jurisdiction, legal form, and status (nested).",
            "registration": "LEI registration metadata: registration status, dates, and managing LOU (nested).",
            "bic": "Business Identifier Code(s) (SWIFT/ISO 9362) associated with the entity, if any.",
            "mic": "Market Identifier Code(s) (ISO 10383) associated with the entity, if any.",
            "ocid": "Open Corporates ID associated with the entity, if any.",
            "conformityFlag": "GLEIF's assessment of how well the record conforms to the LEI data standard.",
            "initial_registration_date": "Date the LEI was first issued. Promoted from `registration.initialRegistrationDate`; stable, used to partition the table.",
            "last_update_date": "Date the LEI record was last updated. Promoted from `registration.lastUpdateDate`; used for incremental sync.",
        },
    },
    "LeiIssuers": {
        "description": "A Local Operating Unit (LOU) accredited by GLEIF to issue and maintain LEIs.",
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "The issuer's own LEI code.",
            "lei": "The issuer's own LEI code.",
            "name": "The issuer's legal name.",
            "marketingName": "The issuer's public-facing/marketing name.",
            "website": "URL of the issuer's LEI-issuance website.",
            "accreditationDate": "Date GLEIF accredited the issuer.",
        },
    },
    "EntityLegalForms": {
        "description": "A jurisdiction's entity legal form (e.g. LLC, GmbH) from the ISO 20275 code list.",
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "The ISO 20275 Entity Legal Form (ELF) code.",
            "code": "The ISO 20275 Entity Legal Form (ELF) code, same as `id`.",
            "country": "Country the legal form applies in.",
            "countryCode": "ISO 3166-1 alpha-2 country code.",
            "jurisdiction": "Subdivision jurisdiction the legal form applies in, if narrower than the country.",
            "dateCreated": "Date this legal form entry was added to the ISO 20275 code list.",
            "status": "Whether the legal form code is active (`ACTV`) or retired (`INAC`).",
            "names": "Localized names and abbreviations for the legal form (nested list).",
        },
    },
    "RegistrationAuthorities": {
        "description": "An official business registry (e.g. a companies house) recognized by GLEIF.",
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "The GLEIF Registration Authority (RA) code.",
            "code": "The GLEIF Registration Authority (RA) code, same as `id`.",
            "internationalName": "The registry's name in English/international form.",
            "localName": "The registry's name in the local language, if different.",
            "website": "URL of the registration authority.",
            "jurisdictions": "Countries and subdivisions this registration authority covers (nested list).",
        },
    },
    "Countries": {
        "description": "An ISO 3166-1 country used to classify LEI records and legal forms.",
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "ISO 3166-1 alpha-2 country code, same as `code`.",
            "code": "ISO 3166-1 alpha-2 country code.",
            "name": "The country's English name.",
        },
    },
    "Jurisdictions": {
        "description": "An ISO 3166-2 jurisdiction (country or country subdivision) used to classify LEI records.",
        "docs_url": "https://www.gleif.org/en/lei-data/gleif-api",
        "columns": {
            "id": "ISO 3166-1/3166-2 jurisdiction code, same as `code`.",
            "code": "ISO 3166-1/3166-2 jurisdiction code (e.g. `US`, `US-CA`).",
            "name": "The jurisdiction's English name.",
            "names": "Localized names for the jurisdiction (nested list).",
        },
    },
}
