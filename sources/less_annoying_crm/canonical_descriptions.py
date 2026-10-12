from sources.sdk import CanonicalDescriptions

# Descriptions taken from the Less Annoying CRM v2 API docs
# (https://account.lessannoyingcrm.com/api_docs/v2). Keyed by the schema/endpoint name from
# `get_schemas`. Partial coverage is fine — anything missing falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "Users on the Less Annoying CRM account.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Settings_Functions/Users",
        "columns": {
            "UserId": "Unique identifier for the user.",
            "FirstName": "The user's first name.",
            "LastName": "The user's last name.",
            "Email": "The user's email address.",
            "Timezone": "The user's configured timezone.",
        },
    },
    "teams": {
        "description": "Teams configured on the account, used to group and share records between users.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Teams",
        "columns": {
            "TeamId": "Unique identifier for the team.",
            "Name": "Display name of the team.",
            "DateCreated": "When the team was created.",
        },
    },
    "contacts": {
        "description": "Contacts and companies in the CRM.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Contacts",
        "columns": {
            "ContactId": "Unique identifier for the contact or company.",
            "IsCompany": "True when the record is a company rather than an individual contact.",
            "CompanyId": "Identifier of the company this contact is associated with, if any.",
            "Name": "Structured name of the contact (first/last and related fields).",
            "DateCreated": "When the contact was created.",
            "LastUpdate": "When the contact was last modified.",
        },
    },
    "tasks": {
        "description": "Tasks (to-dos) tracked in the CRM, optionally linked to a contact.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Tasks",
        "columns": {
            "TaskId": "Unique identifier for the task.",
            "Name": "Short description of the task.",
            "DueDate": "The date the task is due.",
            "IsCompleted": "Whether the task has been completed.",
            "DateCompleted": "When the task was completed, if applicable.",
            "ContactId": "Identifier of the contact the task is linked to, if any.",
            "AssignedTo": "Identifier of the user the task is assigned to.",
            "DateCreated": "When the task was created.",
        },
    },
    "notes": {
        "description": "Notes recorded against contacts and companies in the CRM.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Notes",
        "columns": {
            "NoteId": "Unique identifier for the note.",
            "ContactId": "Identifier of the contact the note belongs to.",
            "Note": "The text body of the note.",
            "UserId": "Identifier of the user who created the note.",
            "DateCreated": "When the note was created.",
            "DateDisplayedInHistory": "The date the note is displayed under in the contact's history.",
        },
    },
    "events": {
        "description": "Calendar events, optionally linked to contacts.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Events",
        "columns": {
            "EventId": "Unique identifier for the event.",
            "Name": "Title of the event.",
            "Date": "The date of the event.",
            "StartTime": "Start time of the event.",
            "EndTime": "End time of the event.",
            "DateCreated": "When the event was created.",
            "DateUpdated": "When the event was last modified.",
        },
    },
    "pipelines": {
        "description": "Pipelines configured on the account, including archived ones. A pipeline tracks deals, leads or other processes through a set of statuses.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Settings_Functions/Pipelines",
        "columns": {
            "PipelineId": "Unique identifier for the pipeline.",
            "Name": "Display name of the pipeline.",
            "Color": "Display color of the pipeline.",
            "DateCreated": "When the pipeline was created.",
            "DateArchived": "When the pipeline was archived, if it has been archived.",
            "Statuses": "The statuses (stages) defined on the pipeline.",
            "Fields": "The custom fields defined on the pipeline's items.",
        },
    },
    "pipeline_statuses": {
        "description": "Statuses (stages) that pipeline items move through, across every pipeline.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Settings_Functions/Pipeline_Statuses",
        "columns": {
            "StatusId": "Unique identifier for the status.",
            "PipelineId": "Identifier of the pipeline the status belongs to.",
            "Name": "Display name of the status.",
            "IsActive": "Whether items in this status are active (false for closed statuses).",
            "Color": "Display color of the status.",
            "DateCreated": "When the status was created.",
        },
    },
    "pipeline_items": {
        "description": "Pipeline items (deals, leads and other tracked processes) attached to contacts, in active and closed statuses of every non-archived pipeline.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Pipeline_Items",
        "columns": {
            "PipelineItemId": "Unique identifier for the pipeline item.",
            "PipelineId": "Identifier of the pipeline the item belongs to.",
            "StatusId": "Identifier of the item's current status in the pipeline.",
            "ContactId": "Identifier of the contact or company the item is attached to.",
            "DateCreated": "When the pipeline item was created.",
            "CreatedBy": "Identifier of the user who created the item.",
            "LastUpdate": "When the pipeline item was last modified.",
            "LastUpdatedBy": "Identifier of the user who last modified the item.",
            "NumberOfUpdates": "How many times the item has been updated.",
            "LastNote": "The most recent note recorded on the item.",
            "PipelineMetaData": "Summary of the item's pipeline, such as its name.",
            "StatusMetaData": "Summary of the item's status, such as its name.",
            "ContactMetaData": "Summary of the attached contact, such as its name and assigned user.",
        },
    },
    "groups": {
        "description": "Groups used to segment contacts and companies.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Settings_Functions/Groups",
        "columns": {
            "GroupId": "Unique identifier for the group.",
            "Name": "Display name of the group.",
            "Sharing": "Who the group is shared with.",
            "TeamIds": "Identifiers of the teams the group is shared with.",
            "Color": "Display color of the group.",
        },
    },
    "group_memberships": {
        "description": "Which contacts and companies belong to which groups. One row per contact per group.",
        "docs_url": "https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Group_Memberships",
        "columns": {
            "GroupId": "Identifier of the group.",
            "ContactId": "Identifier of the contact or company in the group.",
            "ContactMetaData": "Summary of the contact, such as its name and assigned user.",
        },
    },
}
