"""Uploaded people lists: each row creates or updates a person, and the people form a static cohort."""

from products.workflows.backend.facade.contracts import (
    ContactChunkOutcome,
    ContactsCaptureFailed,
    ContactsCohortFilled,
    PeopleImportInvalid,
    ProviderContactsResult,
)
from products.workflows.backend.services.people_import import (
    MAX_PEOPLE_IMPORT_ROW_BYTES,
    MAX_PEOPLE_IMPORT_ROWS,
    start_people_import,
)
from products.workflows.backend.services.provider_cohorts import (
    MAX_SOURCE_NAME_LENGTH,
    customerio_segment_marker,
    described_static_cohorts,
    has_customerio_segment_rules_cohort,
    resend_segment_description,
)
from products.workflows.backend.services.provider_contacts import (
    discard_staged_contacts,
    fail_contacts_cohort,
    fill_contacts_cohort,
    import_contact_chunk,
    send_provider_contact_properties,
    stage_provider_contacts,
    staged_contact_imports,
)

__all__ = [
    "MAX_PEOPLE_IMPORT_ROW_BYTES",
    "MAX_PEOPLE_IMPORT_ROWS",
    "ContactChunkOutcome",
    "ContactsCaptureFailed",
    "ContactsCohortFilled",
    "MAX_SOURCE_NAME_LENGTH",
    "PeopleImportInvalid",
    "ProviderContactsResult",
    "customerio_segment_marker",
    "described_static_cohorts",
    "discard_staged_contacts",
    "has_customerio_segment_rules_cohort",
    "fail_contacts_cohort",
    "fill_contacts_cohort",
    "import_contact_chunk",
    "send_provider_contact_properties",
    "stage_provider_contacts",
    "resend_segment_description",
    "staged_contact_imports",
    "start_people_import",
]
