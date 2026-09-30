from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Flowlu REST API spec (https://www.flowlu.com/api/json/openapien.json);
# developers.flowlu.com is the API host, not a docs site.
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A CRM account in Flowlu — an organization or contact you do business with.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the account.",
            "name": "The account's display name.",
            "type": "The account type (organization or contact).",
        },
    },
    "leads": {
        "description": "A CRM opportunity (Flowlu's API keeps the legacy 'lead' entity name) tracked through a sales pipeline.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the opportunity.",
            "name": "The opportunity's name.",
        },
    },
    "pipelines": {
        "description": "A CRM sales pipeline that opportunities move through.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the pipeline.",
            "name": "The pipeline's name.",
        },
    },
    "pipeline_stages": {
        "description": "A stage of a CRM sales pipeline, resolving the stage an opportunity sits in.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the stage.",
            "name": "The stage's name.",
            "pipeline_id": "The ID of the pipeline this stage belongs to.",
            "ordering": "The stage's position in the pipeline, sorted ascending.",
            "active": "Whether the stage is still in use.",
            "color": "The stage's colour as a hex code.",
            "created_date": "When the stage was created.",
            "created_by": "The ID of the user who created the stage.",
            "updated_date": "When the stage was last changed.",
            "updated_by": "The ID of the user who last changed the stage.",
        },
    },
    "tasks": {
        "description": "A task in Flowlu's task management module.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the task.",
            "name": "The task's title.",
        },
    },
    "projects": {
        "description": "A project in Flowlu's project management module.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the project.",
            "name": "The project's name.",
        },
    },
    "project_stages": {
        "description": "A stage of a project workflow, resolving the stage a project sits in.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the stage.",
            "name": "The stage's name.",
            "fullname": "The stage's full name.",
            "description": "The stage's description.",
            "project_id": "The ID of the project this stage belongs to.",
            "project_type_id": "The ID of the project type whose workflow the stage belongs to.",
            "ordering": "The stage's position in the workflow, sorted ascending.",
            "color": "The stage's colour as a hex code.",
        },
    },
    "invoices": {
        "description": "An invoice issued to a customer in Flowlu's finance module.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the invoice.",
        },
    },
    "invoice_items": {
        "description": "A line item on an invoice, giving revenue per product or service rather than per invoice total.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the line item.",
            "invoice_id": "The ID of the invoice this line item belongs to.",
            "item_id": "The ID of the catalog product or service being billed.",
            "name": "The line item's name.",
            "description": "The line item's description.",
            "ordering": "The line item's position on the invoice, sorted ascending.",
            "quantity": "Quantity billed.",
            "unit_price": "Price per unit.",
            "unit_id": "The ID of the unit the quantity is measured in.",
            "discount": "The discount applied to the line item.",
            "discount_is_percent": "Whether the discount is a percentage (1) or a fixed amount (0).",
            "discount_amount": "The discount as a monetary amount.",
            "sub_total": "The line item total before tax.",
            "tax_total": "Total tax charged on the line item.",
            "total": "The line item total including tax.",
            "paid_total": "Amount paid against the line item.",
            "bcy_paid_total": "Amount paid, converted to the account's base currency.",
            "paid_date": "When the line item was paid.",
            "type": "Whether the row is a billable line (10) or a header (20).",
        },
    },
    "estimates": {
        "description": "An estimate (quote) prepared for a customer in Flowlu's finance module.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the estimate.",
        },
    },
    "customer_payments": {
        "description": "A payment received from a customer, typically applied against an invoice.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the payment.",
        },
    },
    "transactions": {
        "description": "A money transaction (income or expense) recorded in Flowlu's finance module.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the transaction.",
        },
    },
    "agile_issues": {
        "description": "An issue (user story, task, or bug) on a Flowlu agile board.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the issue.",
            "name": "The issue's title.",
        },
    },
    "agile_sprints": {
        "description": "A sprint within a Flowlu agile project.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the sprint.",
            "name": "The sprint's name.",
        },
    },
    "timesheets": {
        "description": "A time-tracking entry logged against tasks or projects in Flowlu.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the timesheet entry.",
        },
    },
    "timelogs": {
        "description": "An individual time log entry behind a timesheet, with the hours, rates, and amounts recorded for one stretch of work.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the time log.",
            "name": "The time log's name.",
            "description": "What the logged time was spent on.",
            "timesheet_id": "The ID of the timesheet this entry rolls up into.",
            "user_id": "The ID of the user the time is logged for.",
            "time_spent": "Time spent, in seconds.",
            "is_manual": "Whether the time was entered by hand rather than tracked by the timer.",
            "is_billable": "Whether the time is billable to the customer.",
            "is_approved": "Whether the time log has been approved.",
            "rate": "The rate used to value the logged time.",
            "billing_rate": "The rate charged to the customer.",
            "employee_cost_rate": "The hourly cost of the employee's work.",
            "amount": "The logged time valued at the rate.",
            "billing_amount": "The amount billed to the customer.",
            "employee_cost_amount": "The cost of the logged time to the business.",
            "currency_id": "The ID of the currency the amounts are in.",
            "start_timestamp": "When the timer was started.",
            "stop_timestamp": "When the timer was stopped.",
            "status": "The time log's status: new (0), running (10), paused (20), or stopped (30).",
            "created_date": "When the time log was created.",
            "created_by": "The ID of the user who created the time log.",
            "updated_date": "When the time log was last changed.",
            "updated_by": "The ID of the user who last changed the time log.",
        },
    },
    "products": {
        "description": "A product or service from Flowlu's product catalog.",
        "docs_url": "https://www.flowlu.com/api/json/openapien.json",
        "columns": {
            "id": "The unique ID of the product.",
            "name": "The product's name.",
        },
    },
}
