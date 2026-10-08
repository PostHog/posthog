from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "Jobs and leads, with their current milestone, contact, location, and lead source.",
        "docs_url": "https://apidocs.acculynx.com/reference/getjobs",
        "columns": {
            "id": "Unique job identifier.",
            "createdDate": "Date and time the job was created.",
            "modifiedDate": "Date and time the job was last modified.",
            "currentMilestone": "Current stage of the job's workflow.",
            "milestoneDate": "Date and time the job last changed milestone.",
        },
    },
    "contacts": {
        "description": "Contacts with their email addresses, phone numbers, mailing address, and billing address.",
        "docs_url": "https://apidocs.acculynx.com/reference/getcontacts",
        "columns": {"id": "Unique contact identifier.", "createdDate": "Date and time the contact was created."},
    },
    "estimates": {
        "description": "Detailed job estimates, including financial totals, profit, and section references.",
        "docs_url": "https://apidocs.acculynx.com/reference/getestimatebyid",
        "columns": {
            "id": "Unique estimate identifier.",
            "estimate_id": "Identifier from the parent estimate listing.",
            "createdDate": "Date and time the estimate was created, in UTC.",
            "isPrimary": "Whether this is the primary estimate for the job.",
        },
    },
    "invoices": {
        "description": "Invoices for each job, including totals, balance due, invoice state, and sections.",
        "docs_url": "https://apidocs.acculynx.com/reference/getinvoicesforjob",
        "columns": {
            "id": "Unique invoice identifier.",
            "job_id": "Identifier of the job whose invoices were requested.",
            "createdDate": "Date and time the invoice was created.",
        },
    },
    "financials": {
        "description": "Job financial summaries with approved job value, balance due, and worksheet section totals.",
        "docs_url": "https://apidocs.acculynx.com/reference/getfinancialsforjob",
        "columns": {
            "id": "Unique financial record identifier.",
            "job_id": "Identifier of the job whose financials were requested.",
        },
    },
    "payments": {
        "description": "Received payments, paid payments, and additional expenses for each job.",
        "docs_url": "https://apidocs.acculynx.com/reference/getpayments",
        "columns": {
            "id": "Unique payment or expense identifier within its job and category.",
            "job_id": "Identifier of the job whose payments were requested.",
            "payment_category": "Payment group: receivedPayments, paidPayments, or additionalExpenses.",
            "parentId": "Identifier of the parent payment for a sub-payment.",
            "amount": "Amount of the payment or expense.",
        },
    },
    "calendars": {
        "description": "Calendars available for the connected AccuLynx location.",
        "docs_url": "https://apidocs.acculynx.com/reference/getcalendars",
        "columns": {"id": "Unique calendar identifier.", "name": "Calendar name."},
    },
    "calendar_appointments": {
        "description": "Calendar appointments within the configured date range, including attendees and job references.",
        "docs_url": "https://apidocs.acculynx.com/reference/getappointments",
        "columns": {
            "id": "Appointment identifier.",
            "calendar_id": "Identifier of the calendar whose appointments were requested.",
            "start": "Appointment start date and time.",
            "end": "Appointment end date and time.",
        },
    },
    "lead_sources": {
        "description": "Active lead sources for the connected location, including child lead sources.",
        "docs_url": "https://apidocs.acculynx.com/reference/getactiveleadsources",
        "columns": {"id": "Unique lead source identifier.", "name": "Lead source name."},
    },
    "users": {
        "description": "Company users across active, inactive, archived, and deleted statuses.",
        "docs_url": "https://apidocs.acculynx.com/reference/getusers",
        "columns": {"id": "Unique user identifier.", "status": "Current user status.", "role": "User role."},
    },
}
