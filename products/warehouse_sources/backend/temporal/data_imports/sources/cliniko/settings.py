"""Cliniko source settings and constants."""

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every endpoint here is a top-level list resource returning `{<name>: [...], total_entries, links}`,
# with `id` / `created_at` / `updated_at` on every record (per the Cliniko OpenAPI spec at
# https://docs.api.cliniko.com/openapi). `bookings` (a union of appointments + unavailable blocks) is
# deliberately left out, since it would just duplicate `individual_appointments`/`group_appointments`.
ENDPOINTS = (
    "appointment_types",
    "attendees",
    "billable_items",
    "businesses",
    "concession_types",
    "contacts",
    "daily_availabilities",
    "group_appointments",
    "individual_appointments",
    "invoice_items",
    "invoices",
    "patient_cases",
    "patients",
    "practitioners",
    "product_suppliers",
    "products",
    "referral_source_types",
    "referral_sources",
    "treatment_notes",
    "users",
)

# Every endpoint's records carry a `created_at` that never changes after creation, so it's a
# stable partition key even though sync watermarks on `updated_at`.
PARTITION_KEY = "created_at"

PRIMARY_KEY = ["id"]

PAGE_SIZE = 100

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name in ENDPOINTS
}
