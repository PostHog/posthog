from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "Customers for whom the company performs work.",
        "docs_url": "https://help.fieldpulse.com/api-reference/customers/retrieve-customers-list",
        "columns": {},
    },
    "jobs": {
        "description": "Work orders for customers, with scheduling and status information.",
        "docs_url": "https://help.fieldpulse.com/api-reference/jobs/retrieve-jobs-list",
        "columns": {},
    },
    "estimates": {
        "description": "Customer proposals that can become invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/estimates/retrieve-estimates-list",
        "columns": {},
    },
    "invoices": {
        "description": "Invoices sent to customers to collect payment for work.",
        "docs_url": "https://help.fieldpulse.com/api-reference/invoices/list-invoices",
        "columns": {},
    },
    "payments": {
        "description": "Payments recorded against invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/payments/retrieve-payments-list",
        "columns": {},
    },
    "projects": {
        "description": "Projects that group related jobs, estimates, and invoices.",
        "docs_url": "https://help.fieldpulse.com/api-reference/projects/retrieve-projects-list",
        "columns": {},
    },
    "users": {
        "description": "Users of the company account, such as technicians and office staff.",
        "docs_url": "https://help.fieldpulse.com/api-reference/users/retrieve-users-list",
        "columns": {},
    },
    "job_status_workflows": {
        "description": "Status workflows that define the sequence of statuses a job moves through.",
        "docs_url": "https://help.fieldpulse.com/api-reference/jobs/retrieve-job-status-workflows-list",
        "columns": {},
    },
    "job_status_workflow_statuses": {
        "description": "Statuses that belong to the job status workflows.",
        "docs_url": "https://help.fieldpulse.com/api-reference/jobs/retrieve-job-status-workflow-statuses-list",
        "columns": {},
    },
    "pipeline_statuses": {
        "description": "Pipeline statuses that track a customer through the sales pipeline.",
        "docs_url": "https://help.fieldpulse.com/api-reference/pipeline-status/retrieve-pipeline-statuses-list",
        "columns": {},
    },
    "lead_sources": {
        "description": "Lead sources that record how a customer found the company.",
        "docs_url": "https://help.fieldpulse.com/api-reference/lead-source/retrieve-lead-sources-list",
        "columns": {},
    },
    "tags": {
        "description": "Tags that label customers and jobs.",
        "docs_url": "https://help.fieldpulse.com/api-reference/tags/retrieve-tags-list",
        "columns": {},
    },
    "timesheets": {
        "description": "Timesheet entries that record when users clock in and out.",
        "docs_url": "https://help.fieldpulse.com/api-reference/timesheets/retrieve-timesheets-list",
        "columns": {},
    },
    "teams": {
        "description": "Teams of users in the company account.",
        "docs_url": "https://help.fieldpulse.com/api-reference/teams/retrieve-company-teams-list",
        "columns": {},
    },
    "items": {
        "description": "Items that can be added to invoices and estimates.",
        "docs_url": "https://help.fieldpulse.com/api-reference/items/retrieve-items-list",
        "columns": {},
    },
}
