from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the public Teamwork.com Projects V3 API docs (https://apidocs.teamwork.com). Partial
# coverage is fine — any endpoint/column not listed here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects in the Teamwork account, each grouping tasks, milestones, time, and people.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/v3/projects/get-projects-api-v3-projects-json",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Name of the project.",
            "description": "Free-text description of the project.",
            "status": "Project status (e.g. active, archived, completed).",
            "companyId": "Identifier of the company that owns the project.",
            "startDate": "Scheduled start date of the project.",
            "endDate": "Scheduled end date of the project.",
        },
    },
    "tasks": {
        "description": "Tasks across all projects the connected user can access.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/endpoints-by-object/tasks/get-projects-api-v3-tasks-json",
        "columns": {
            "id": "Unique identifier for the task.",
            "name": "Name of the task.",
            "status": "Task status (e.g. new, completed, deleted).",
            "tasklistId": "Identifier of the task list the task belongs to.",
            "parentTaskId": "Identifier of the parent task, when this is a subtask.",
            "priority": "Task priority (e.g. low, medium, high).",
            "startDate": "Date the task is scheduled to start.",
            "dueDate": "Date the task is due.",
            "dateUpdated": "Timestamp the task was last updated.",
        },
    },
    "tasklists": {
        "description": "Task lists, which group related tasks within a project.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/endpoints-by-object/task-lists/get-projects-api-v3-tasklists-json",
        "columns": {
            "id": "Unique identifier for the task list.",
            "name": "Name of the task list.",
            "projectId": "Identifier of the project the task list belongs to.",
            "status": "Task list status (e.g. active, archived).",
            "dateUpdated": "Timestamp the task list was last updated.",
        },
    },
    "milestones": {
        "description": "Milestones marking key dates and deliverables within projects.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/endpoints-by-object/milestones/get-projects-api-v3-milestones-json",
        "columns": {
            "id": "Unique identifier for the milestone.",
            "name": "Name of the milestone.",
            "projectId": "Identifier of the project the milestone belongs to.",
            "deadline": "Date the milestone is due.",
            "completed": "Whether the milestone has been completed.",
            "dateCreated": "Timestamp the milestone was created.",
            "dateUpdated": "Timestamp the milestone was last updated.",
        },
    },
    "timelogs": {
        "description": "Logged time entries across all projects and tasks.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/endpoints-by-object/time-tracking/get-projects-api-v3-time-json",
        "columns": {
            "id": "Unique identifier for the time entry.",
            "projectId": "Identifier of the project the time was logged against.",
            "taskId": "Identifier of the task the time was logged against, when applicable.",
            "userId": "Identifier of the user who logged the time.",
            "description": "Description of the work the time entry covers.",
            "minutes": "Duration of the time entry in minutes.",
            "billable": "Whether the time entry is billable.",
            "dateCreated": "Timestamp the time entry was created.",
            "dateEdited": "Timestamp the time entry was last edited.",
        },
    },
    "people": {
        "description": "People (users) in the Teamwork account.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/endpoints-by-object/people/get-projects-api-v3-people-json",
        "columns": {
            "id": "Unique identifier for the person.",
            "firstName": "Person's first name.",
            "lastName": "Person's last name.",
            "email": "Person's email address.",
            "companyId": "Identifier of the company the person belongs to.",
            "isAdmin": "Whether the person is an account administrator.",
        },
    },
    "companies": {
        "description": "Companies (clients and the owner organization) in the Teamwork account.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/v3/companies/get-projects-api-v3-companies-json",
        "columns": {
            "id": "Unique identifier for the company.",
            "name": "Name of the company.",
            "email": "Primary email address for the company.",
            "phone": "Primary phone number for the company.",
            "countryCode": "Country code of the company's address.",
        },
    },
    "tags": {
        "description": "Tags used to label projects, tasks, and other entities.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/v3/tags/get-projects-api-v3-tags-json",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
            "color": "Display color of the tag.",
        },
    },
    "comments": {
        "description": "Comments left on projects, tasks, milestones, and other entities.",
        "docs_url": "https://apidocs.teamwork.com/docs/teamwork/v3/comments/get-projects-api-v3-comments-json",
        "columns": {
            "id": "Unique identifier for the comment.",
            "body": "Text content of the comment.",
            "authorId": "Identifier of the user who wrote the comment.",
            "objectType": "Type of entity the comment is attached to (e.g. task, milestone).",
            "objectId": "Identifier of the entity the comment is attached to.",
        },
    },
}
