"""ServiceM8 endpoint catalog.

Field service management API for trades businesses. Every object exposes `uuid`
(globally unique across the account), `active` (soft-delete flag), and `edit_date`
(last-modified timestamp), which is what this source syncs on.
Reference: https://developer.servicem8.com/reference
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Display name -> vendor object name, e.g. "Job" -> GET /api_1.0/job.json.
ENDPOINT_PATHS: dict[str, str] = {
    "Job": "job",
    "Company": "company",
    "CompanyContact": "companycontact",
    "Staff": "staff",
    "Category": "category",
    "JobActivity": "jobactivity",
    "JobMaterial": "jobmaterial",
    "JobPayment": "jobpayment",
    "Note": "note",
    "Attachment": "attachment",
}

ENDPOINTS: tuple[str, ...] = tuple(ENDPOINT_PATHS)

# Every listed object supports `$filter=edit_date gt '<value>'` (see /docs/filtering).
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [incremental_field("edit_date")] for name in ENDPOINTS}

# `uuid` is assigned per-record account-wide, not scoped to a parent, so it's unique across
# every endpoint without composing in a parent id.
PRIMARY_KEY = "uuid"
