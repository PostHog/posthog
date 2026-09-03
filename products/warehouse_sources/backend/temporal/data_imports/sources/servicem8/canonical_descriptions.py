"""Canonical, documentation-sourced descriptions for ServiceM8 endpoints and columns.

Sourced from the official ServiceM8 API reference (https://developer.servicem8.com/reference).
Keyed by the display names in `settings.py` `ENDPOINT_PATHS`, which match the
`ExternalDataSchema.name` of a synced ServiceM8 table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields present on almost every ServiceM8 object; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "uuid": "Unique identifier for the record.",
    "active": "Whether the record is active; 0 means it has been deleted.",
    "edit_date": "Timestamp at which the record was last modified.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Job": {
        "description": "A job (quote, work order, or completed job) for a client.",
        "docs_url": "https://developer.servicem8.com/reference/listjobs",
        "columns": _columns(
            date="Job creation or scheduled date.",
            status="Job status: Quote, Work Order, Unsuccessful, or Completed.",
            company_uuid="UUID of the client the job belongs to.",
            job_address="Physical address the work is carried out at.",
            job_description="Description of the work to be done.",
            work_done_description="Description of the work that was completed.",
            generated_job_id="System-assigned, human-readable job number.",
            category_uuid="UUID of the job's category.",
            created_by_staff_uuid="UUID of the staff member who created the job.",
            completion_date="Timestamp the job was marked completed.",
            payment_received="Whether payment has been received for the job.",
            lat="Latitude of the job address.",
            lng="Longitude of the job address.",
        ),
    },
    "Company": {
        "description": "A client (company) that jobs are performed for.",
        "docs_url": "https://developer.servicem8.com/reference/listclients",
        "columns": _columns(
            name="Client company name.",
            is_individual="Whether the client is an individual rather than a company.",
            address="Client's primary address.",
            billing_address="Client's billing address.",
            website="Client's website URL.",
            parent_company_uuid="UUID of a parent company, if this client is a sub-company.",
            tax_rate_uuid="UUID of the default tax rate applied to this client.",
            payment_terms="Default payment terms for this client.",
        ),
    },
    "CompanyContact": {
        "description": "A contact person associated with a client company.",
        "docs_url": "https://developer.servicem8.com/reference/listcompanycontacts",
        "columns": _columns(
            company_uuid="UUID of the client company this contact belongs to.",
            is_primary_contact="Whether this is the client's primary contact.",
            first="Contact's first name.",
            last="Contact's last name.",
            phone="Contact's primary phone number.",
            mobile="Contact's mobile phone number.",
            email="Contact's email address.",
            type="Contact type, e.g. BILLING or JOB.",
        ),
    },
    "Staff": {
        "description": "A staff member (technician or office user) in the account.",
        "docs_url": "https://developer.servicem8.com/reference/liststaffmembers",
        "columns": _columns(
            first="Staff member's first name.",
            last="Staff member's last name.",
            email="Staff member's email address.",
            mobile="Staff member's mobile phone number.",
            job_title="Staff member's job title.",
            security_role_uuid="UUID of the staff member's security role.",
        ),
    },
    "Category": {
        "description": "A job category used to organize and color-code jobs.",
        "docs_url": "https://developer.servicem8.com/reference/listcategories",
        "columns": _columns(
            name="Category name.",
            colour="Hexadecimal colour code used to display the category.",
        ),
    },
    "JobActivity": {
        "description": "A scheduled or recorded block of time a staff member spent on a job.",
        "docs_url": "https://developer.servicem8.com/reference/listjobactivities",
        "columns": _columns(
            job_uuid="UUID of the job this activity belongs to.",
            staff_uuid="UUID of the staff member assigned to this activity.",
            start_date="Scheduled or recorded start time of the activity.",
            end_date="Scheduled or recorded end time of the activity.",
            travel_time_in_seconds="Estimated travel time to the job, in seconds.",
            travel_distance_in_meters="Estimated travel distance to the job, in meters.",
        ),
    },
    "JobMaterial": {
        "description": "A line item for materials or labor used on a job.",
        "docs_url": "https://developer.servicem8.com/reference/listjobmaterials",
        "columns": _columns(
            job_uuid="UUID of the job this material line belongs to.",
            material_uuid="UUID of the catalog material used, if any.",
            name="Name of the material as displayed on invoices and quotes.",
            quantity="Quantity of the material used.",
            price="Unit price of the material, excluding tax.",
            cost="Cost of the material to the business, excluding tax.",
            tax_rate_uuid="UUID of the tax rate applied to this line.",
        ),
    },
    "JobPayment": {
        "description": "A payment recorded against a job.",
        "docs_url": "https://developer.servicem8.com/reference/listjobpayments",
        "columns": _columns(
            job_uuid="UUID of the job this payment applies to.",
            actioned_by_uuid="UUID of the staff member who recorded the payment.",
            timestamp="Date and time the payment was recorded.",
            amount="Payment amount, in the account's currency.",
            method="Payment method, e.g. Cash, Credit Card, or Bank Transfer.",
            is_deposit="Whether this payment is a deposit rather than a completion payment.",
        ),
    },
    "Note": {
        "description": "A note attached to a job, client, or other object.",
        "docs_url": "https://developer.servicem8.com/reference/listnotes",
        "columns": _columns(
            related_object="Type of object this note is attached to.",
            related_object_uuid="UUID of the object this note is attached to.",
            note="Text content of the note.",
            action_required="Whether the note requires a follow-up action.",
            create_date="Timestamp the note was created.",
        ),
    },
    "Attachment": {
        "description": "Metadata for a file (photo, document, or signature) attached to a job or other object.",
        "docs_url": "https://developer.servicem8.com/reference/listattachments",
        "columns": _columns(
            related_object="Type of object this attachment is attached to.",
            related_object_uuid="UUID of the object this attachment is attached to.",
            attachment_name="Display name of the attached file.",
            file_type="File extension of the attachment, including the leading dot.",
            attachment_source="Source of the attachment, e.g. INVOICE or QUOTE.",
            is_favourite="Whether the attachment is marked as a favourite.",
        ),
    },
}
