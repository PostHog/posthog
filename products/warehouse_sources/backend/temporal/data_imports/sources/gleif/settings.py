from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.gleif.org/api/v1"

# GLEIF caps `page[size]` at 200 (verified live; 201 returns 400).
PAGE_SIZE = 200

LEI_RECORDS = "LeiRecords"
LEI_ISSUERS = "LeiIssuers"
ENTITY_LEGAL_FORMS = "EntityLegalForms"
REGISTRATION_AUTHORITIES = "RegistrationAuthorities"
COUNTRIES = "Countries"
JURISDICTIONS = "Jurisdictions"

ENDPOINTS = (
    LEI_RECORDS,
    LEI_ISSUERS,
    ENTITY_LEGAL_FORMS,
    REGISTRATION_AUTHORITIES,
    COUNTRIES,
    JURISDICTIONS,
)

ENDPOINT_PATHS: dict[str, str] = {
    LEI_RECORDS: "/lei-records",
    LEI_ISSUERS: "/lei-issuers",
    ENTITY_LEGAL_FORMS: "/entity-legal-forms",
    REGISTRATION_AUTHORITIES: "/registration-authorities",
    COUNTRIES: "/countries",
    JURISDICTIONS: "/jurisdictions",
}

# Only `lei-records` exposes a server-side timestamp filter (verified live:
# `filter[registration.lastUpdateDate]=>=DATE`). The reference tables (issuers, legal forms,
# registration authorities, countries, jurisdictions) change rarely and expose no filter, so
# they sync full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    LEI_RECORDS: [incremental_field("last_update_date")],
}
