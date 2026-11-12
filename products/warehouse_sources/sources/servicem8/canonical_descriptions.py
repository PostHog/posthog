"""Canonical, documentation-sourced descriptions for ServiceM8 endpoints and columns.

Sourced from the official ServiceM8 API reference (https://developer.servicem8.com/reference).
Keyed by the display names in `settings.py` `ENDPOINT_PATHS`, which match the
`ExternalDataSchema.name` of a synced ServiceM8 table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "Material": {
        "description": "An inventory item, product, or labour rate that can be added to jobs.",
        "docs_url": "https://developer.servicem8.com/reference/listmaterials",
        "columns": _columns(
            name="Name of the material, product, or labour rate.",
            item_number="Item code for the material, unique within the account.",
            item_description="Description of the material.",
            price="Selling price; includes tax when price_includes_taxes is 1.",
            cost="Purchase cost; includes tax when price_includes_taxes is 1.",
            price_includes_taxes="Whether price and cost include tax (1) or exclude it (0).",
            tax_rate_uuid="UUID of the tax rate applied to the material.",
            quantity_in_stock="Current quantity of the material in stock.",
            item_is_inventoried="Whether stock levels are tracked for the material.",
            barcode="Barcode (UPC, EAN, or other format) of the material.",
        ),
    },
    "TaxRate": {
        "description": "A named tax rate (for example GST or VAT) applied to materials and invoices.",
        "docs_url": "https://developer.servicem8.com/reference/listtaxrates",
        "columns": _columns(
            name="Name of the tax rate, such as GST or VAT.",
            amount="Tax rate as a percentage, e.g. 10 for 10%.",
            is_default_tax_rate="Whether this is the account's default tax rate.",
        ),
    },
    "StaffTimeEvent": {
        "description": "A staff clock-on, clock-off, or lunch-break event, separate from job check-ins.",
        "docs_url": "https://developer.servicem8.com/reference/liststafftimeevents",
        "columns": _columns(
            staff_uuid="UUID of the staff member the event belongs to.",
            timestamp="Event time in the account timezone (YYYY-MM-DD HH:MM:SS).",
            event_name="Action recorded: CLOCK_ON, CLOCK_OFF, LUNCH_START, or LUNCH_END.",
            source="Origin of the recorded event.",
        ),
    },
    "Feedback": {
        "description": "A customer feedback rating and comment, usually about a job.",
        "docs_url": "https://developer.servicem8.com/reference/listfeedback",
        "columns": _columns(
            timestamp="Date and time the feedback was submitted.",
            related_object="Type of object the feedback is about, usually job or vendor.",
            related_object_uuid="UUID of the object the feedback is about.",
            rating="Rating from 1 to 5; higher is more positive.",
            comment="Text comment left with the feedback.",
        ),
    },
    "JobQueue": {
        "description": "A job queue that holds jobs awaiting action, such as Workshop or Pending Quotes.",
        "docs_url": "https://developer.servicem8.com/reference/listjobqueues",
        "columns": _columns(
            name="Name of the job queue.",
            default_timeframe="Default number of days a job stays in the queue before it needs attention.",
            subscribed_staff="Semicolon-delimited list of UUIDs of staff subscribed to queue notifications.",
            requires_assignment="Whether jobs in the queue must be assigned to a staff member.",
        ),
    },
    "Badge": {
        "description": "A badge used to classify jobs and clients, such as Warranty or VIP.",
        "docs_url": "https://developer.servicem8.com/reference/listbadges",
        "columns": _columns(
            name="Display name of the badge.",
            regarding_asset_type_uuid="UUID of the asset type the badge represents, for asset-based badges.",
        ),
    },
    "JobMaterialBundle": {
        "description": "A bundle of materials added to a job as one line item on its quote or invoice.",
        "docs_url": "https://developer.servicem8.com/reference/listjobmaterialbundles",
        "columns": _columns(
            job_uuid="UUID of the job the bundle belongs to.",
            material_bundle_uuid="UUID of the material bundle this job bundle was created from.",
            item_number="Item number of the bundle, shown on the quote or invoice.",
            name="Name of the bundle, shown on the quote or invoice.",
            quantity="Quantity of the bundle line item on the invoice.",
            sort_order="Display order of the bundle among the job's materials; lower values show first.",
        ),
    },
    "JobContact": {
        "description": "A contact person for a job, such as the job contact or the billing contact.",
        "docs_url": "https://developer.servicem8.com/reference/listjobcontacts",
        "columns": _columns(
            job_uuid="UUID of the job the contact belongs to.",
            first="First name of the contact.",
            last="Last name of the contact.",
            phone="Landline or office phone number of the contact.",
            mobile="Mobile phone number of the contact.",
            email="Email address of the contact.",
            type="Relationship of the contact to the job: JOB, BILLING, or Property Manager.",
        ),
    },
}
