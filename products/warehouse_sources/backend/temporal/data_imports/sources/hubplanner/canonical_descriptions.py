from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the official Hub Planner API docs (https://github.com/hubplanner/API).
# Keys are the endpoint names returned by `get_schemas` (see settings.ENDPOINTS).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects scheduled in Hub Planner, including budget, status and assigned resources/managers.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/project.md",
        "columns": {
            "_id": "Unique identifier for the project.",
            "name": "Project name.",
            "note": "Free-text note on the project.",
            "projectCode": "User-defined project code.",
            "status": "Project status (e.g. STATUS_ACTIVE, STATUS_ARCHIVED).",
            "budgetHours": "Project budget expressed in hours.",
            "budgetCashAmount": "Project budget expressed as a cash amount.",
            "budgetCurrency": "Currency of the cash budget.",
            "projectManagers": "IDs of the resources managing the project.",
            "resources": "IDs of the resources assigned to the project.",
            "start": "Project start date.",
            "end": "Project end date.",
            "createdDate": "Date the project was created.",
            "updatedDate": "Date the project was last updated.",
        },
    },
    "resources": {
        "description": "Resources (people or assets) that can be scheduled, with role, status and contact details.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/resource.md",
        "columns": {
            "_id": "Unique identifier for the resource.",
            "firstName": "Resource first name.",
            "lastName": "Resource last name.",
            "email": "Resource email address.",
            "role": "Resource role.",
            "status": "Resource status (e.g. STATUS_ACTIVE, STATUS_ARCHIVED).",
            "createdDate": "Date the resource was created.",
            "updatedDate": "Date the resource was last updated.",
        },
    },
    "bookings": {
        "description": "Scheduled bookings allocating a resource to a project over a date range.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/bookings.md",
        "columns": {
            "_id": "Unique identifier for the booking.",
            "title": "Booking title.",
            "state": "Booking state (STATE_DAY_MINUTE, STATE_PERCENTAGE, STATE_TOTAL_MINUTE).",
            "type": "Booking type (SCHEDULED, APPROVED, WAITING_FOR_APPROVAL, REJECTED).",
            "stateValue": "Value interpreted according to the booking state.",
            "start": "Booking start date.",
            "end": "Booking end date.",
            "resource": "ID of the booked resource.",
            "project": "ID of the project the booking is for.",
            "note": "Booking note.",
            "createdDate": "Date the booking was created.",
            "updatedDate": "Date the booking was last updated.",
        },
    },
    "time_entries": {
        "description": "Timesheet entries logging time a resource spent on a project.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/timesheets.md",
        "columns": {
            "_id": "Unique identifier for the time entry.",
            "resource": "ID of the resource who logged the time.",
            "project": "ID of the project the time was logged against.",
            "status": "Entry status (UNSUBMITTED, SUBMITTED, APPROVED, REJECTED, PENDING).",
            "createdDate": "Server date when the entry was created.",
            "updatedDate": "Server date when the entry was last updated.",
        },
    },
    "events": {
        "description": "Custom events in the scheduler (e.g. training, meetings) not tied to a project.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/events.md",
        "columns": {
            "_id": "Unique identifier for the event.",
            "name": "Event name.",
            "eventCode": "User-defined event code.",
            "createdDate": "Date the event was created.",
            "updatedDate": "Date the event was last updated.",
        },
    },
    "clients": {
        "description": "Clients that projects can be associated with.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/clients.md",
        "columns": {
            "_id": "Unique identifier for the client.",
            "name": "Client name.",
            "createdDate": "Date the client was created.",
            "updatedDate": "Date the client was last updated.",
        },
    },
    "milestones": {
        "description": "Project milestones with a target date.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/milestones.md",
        "columns": {
            "_id": "Unique identifier for the milestone.",
            "name": "Milestone name.",
            "date": "Milestone date.",
            "project": "ID of the project the milestone belongs to.",
        },
    },
    "project_groups": {
        "description": "Groups used to organise projects.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/groups.md",
        "columns": {
            "_id": "Unique identifier for the group.",
            "createdDate": "Date the group was created.",
            "updatedDate": "Date the group was last updated.",
        },
    },
    "resource_groups": {
        "description": "Groups used to organise resources.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/groups.md",
        "columns": {
            "_id": "Unique identifier for the group.",
            "createdDate": "Date the group was created.",
            "updatedDate": "Date the group was last updated.",
        },
    },
    "billing_rates": {
        "description": "Billing rates that can be applied to bookings and projects.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/billingrate.md",
        "columns": {
            "_id": "Unique identifier for the billing rate.",
            "label": "Billing rate label.",
            "currency": "Currency of the rate.",
            "createdDate": "Date the billing rate was created.",
            "updatedDate": "Date the billing rate was last updated.",
        },
    },
    "holidays": {
        "description": "Public holidays configured in Hub Planner.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/holidays.md",
        "columns": {
            "_id": "Unique identifier for the holiday.",
            "name": "Holiday name.",
            "createdDate": "Date the holiday was created.",
            "updatedDate": "Date the holiday was last updated.",
        },
    },
    "vacations": {
        "description": "Vacation and time-off entries per resource.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/vacation.md",
        "columns": {
            "_id": "Unique identifier for the vacation entry.",
            "title": "Vacation title.",
            "start": "Vacation start date.",
            "end": "Vacation end date.",
            "resource": "ID of the resource the vacation belongs to.",
            "type": "Vacation type (e.g. APPROVED, REJECTED).",
            "state": "Vacation state.",
        },
    },
    "project_managers": {
        "description": "Resources designated as project managers.",
        "docs_url": "https://github.com/hubplanner/API/blob/master/Sections/project-manager.md",
        "columns": {
            "_id": "Unique identifier for the project manager record.",
            "createdDate": "Date the record was created.",
            "updatedDate": "Date the record was last updated.",
        },
    },
}
