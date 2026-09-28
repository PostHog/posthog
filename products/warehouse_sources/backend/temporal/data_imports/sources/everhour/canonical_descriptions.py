"""Canonical, documentation-sourced descriptions for Everhour endpoints and columns.

Sourced from the official Everhour API reference (https://everhour.docs.apiary.io/). Keyed by the
endpoint names in `settings.py` `EVERHOUR_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Everhour table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://everhour.docs.apiary.io/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A client (customer) in the Everhour account that projects can be associated with.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the client.",
            "name": "Name of the client.",
            "projects": "Project ids associated with this client.",
            "businessDetails": "Free-form billing/business details stored for the client.",
            "createdAt": "When the client was created.",
        },
    },
    "projects": {
        "description": "A project tracked in Everhour, including its budget settings and total tracked time.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the project. Integration projects are prefixed (e.g. 'as:' for Asana, 'tr:' for Trello).",
            "name": "Name of the project.",
            "type": "Project type (e.g. 'board') or the integration platform it originates from.",
            "workspaceId": "Identifier of the workspace the project belongs to.",
            "status": "Project status (e.g. 'open', 'archived').",
            "billing": "Billing configuration for the project (type and rate).",
            "budget": "Budget configuration for the project.",
            "client": "Identifier of the client the project belongs to, if any.",
            "createdAt": "When the project was created.",
        },
    },
    "users": {
        "description": "A member of the Everhour team.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "Display name of the user.",
            "email": "Email address of the user.",
            "role": "Role of the user within the team (e.g. 'admin', 'member').",
            "status": "Account status of the user (e.g. 'active', 'invited', 'removed').",
            "rate": "Configured billing/cost rate for the user.",
            "capacity": "Weekly work capacity configured for the user, in seconds.",
        },
    },
    "tasks": {
        "description": "A task within a project. Fanned out over every project, with the parent project id injected as `project_id`.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the task. Integration tasks are prefixed (e.g. 'as:' for Asana, 'jira:' for Jira).",
            "project_id": "Identifier of the parent project this task row was fetched under (injected by the connector).",
            "name": "Name of the task.",
            "type": "Task type (e.g. 'task').",
            "status": "Task status (e.g. 'open', 'completed').",
            "projects": "Project ids the task belongs to.",
            "time": "Tracked time totals for the task, in seconds.",
            "estimate": "Time estimate configured for the task.",
            "labels": "Labels/tags applied to the task.",
            "createdAt": "When the task was created.",
        },
    },
    "time_records": {
        "description": "Individual time entries logged against tasks. Supports incremental sync via the server-side from/to date window.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the time record.",
            "date": "Calendar date the time was logged for (YYYY-MM-DD).",
            "time": "Duration logged, in seconds.",
            "user": "The user who logged the time (nested object with id, name, avatar).",
            "task": "The task the time was logged against (nested object with id, name and its projects).",
            "comment": "Optional free-text comment on the time record.",
            "isLocked": "Whether the time record is locked from further edits.",
            "createdAt": "When the time record was created.",
        },
    },
    "invoices": {
        "description": "A client invoice, including its line items, totals and billing period.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the invoice.",
            "client": "The client the invoice was raised for (nested client object).",
            "createdBy": "The user who created the invoice (nested user object).",
            "createdAt": "When the invoice was created.",
            "issueDate": "Date the invoice was issued.",
            "dueDate": "Date payment is due.",
            "dateFrom": "Start of the period the invoice covers.",
            "dateTill": "End of the period the invoice covers.",
            "invoiceItems": "Line items on the invoice, each with a name, billed time and amounts.",
            "publicId": "Human-facing invoice number shown to the client.",
            "status": "Invoice status: 'draft', 'sent' or 'paid'.",
            "projects": "Project ids the invoice draws its time and expenses from.",
            "includeTime": "Whether tracked time is billed on this invoice.",
            "includeExpenses": "Whether expenses are billed on this invoice.",
            "discount": "Discount applied to the invoice (rate and amount in cents).",
            "tax": "Tax applied to the invoice (rate and amount in cents).",
            "listAmount": "Amount in cents before discount and taxes.",
            "netAmount": "Amount in cents with the discount applied but before taxes.",
            "totalAmount": "Amount in cents with both discount and taxes applied.",
            "totalTime": "Total time billed on the invoice, in seconds.",
        },
    },
    "expenses": {
        "description": "A cost recorded against a project, used alongside time records for margin and billing.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the expense.",
            "date": "Calendar date the expense was incurred (YYYY-MM-DD).",
            "amount": "Expense amount, in cents.",
            "category": "Identifier of the expense category.",
            "project": "Identifier of the project the expense belongs to.",
            "user": "Identifier of the user who recorded the expense.",
            "billable": "Whether the expense can be billed to the client.",
            "quantity": "Number of units, for unit-based categories such as mileage.",
            "details": "Free-text notes on the expense.",
            "attachments": "Receipts and other files attached to the expense.",
        },
    },
    "timecards": {
        "description": "Clock-in and clock-out attendance per user per day. Separate from time records, which log time against tasks.",
        "docs_url": _DOCS_URL,
        "columns": {
            "user": "Identifier of the user the timecard belongs to.",
            "date": "Calendar date the timecard covers (YYYY-MM-DD).",
            "clockIn": "Clock-in time, in the user's timezone.",
            "clockOut": "Clock-out time, in the user's timezone.",
            "breakTime": "Total break duration, in seconds.",
            "workTime": "Working time in seconds: clock-out minus clock-in minus breaks.",
            "history": "Ordered record of every clock-in, clock-out and break change on the day.",
        },
    },
    "assignments": {
        "description": "Planned work and time off from the resource planner, giving the scheduled counterpart to logged time records.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the assignment.",
            "user": "Identifier of the user the work is scheduled for.",
            "project": "Identifier of the project the work is scheduled against.",
            "type": "Whether the entry is scheduled project work or time off.",
            "startDate": "First day of the scheduled period.",
            "endDate": "Last day of the scheduled period.",
            "days": "Number of workdays the assignment spans.",
            "time": "Scheduled time across the period, in seconds.",
        },
    },
}
