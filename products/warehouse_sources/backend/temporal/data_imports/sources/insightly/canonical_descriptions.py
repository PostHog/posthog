from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api.insightly.com/v3.1/Help"

# Fields shared by every Insightly object. Merged into each endpoint's columns below.
_COMMON_COLUMNS = {
    "DATE_CREATED_UTC": "UTC timestamp when the record was created.",
    "DATE_UPDATED_UTC": "UTC timestamp when the record was last modified (the incremental cursor).",
    "OWNER_USER_ID": "User ID of the record owner.",
    "CREATED_USER_ID": "User ID of the user who created the record.",
    "VISIBLE_TO": "Sharing scope of the record (e.g. EVERYONE, OWNER, TEAM, INDIVIDUAL).",
    "CUSTOMFIELDS": "List of custom field values defined for your Insightly account.",
    "TAGS": "List of tags applied to the record.",
}


def _columns(**extra: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **extra}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Contacts": {
        "description": "People tracked in Insightly, with their contact details and relationships.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            CONTACT_ID="Unique identifier for the contact.",
            FIRST_NAME="Contact's first name.",
            LAST_NAME="Contact's last name.",
            EMAIL_ADDRESS="Primary email address of the contact.",
            ORGANISATION_ID="ID of the organisation the contact belongs to, if any.",
            TITLE="Contact's job title.",
            PHONE="Primary phone number of the contact.",
        ),
    },
    "Organisations": {
        "description": "Companies and organisations tracked in Insightly.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            ORGANISATION_ID="Unique identifier for the organisation.",
            ORGANISATION_NAME="Name of the organisation.",
            PHONE="Primary phone number of the organisation.",
            WEBSITE="Organisation's website URL.",
        ),
    },
    "Opportunities": {
        "description": "Sales opportunities (deals) tracked through your pipelines.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            OPPORTUNITY_ID="Unique identifier for the opportunity.",
            OPPORTUNITY_NAME="Name of the opportunity.",
            OPPORTUNITY_STATE="Current state of the opportunity (e.g. OPEN, WON, LOST, ABANDONED).",
            OPPORTUNITY_VALUE="Monetary value of the opportunity.",
            PROBABILITY="Estimated probability (%) of winning the opportunity.",
            BID_CURRENCY="Currency code for the opportunity value.",
            PIPELINE_ID="ID of the pipeline the opportunity is in.",
            STAGE_ID="ID of the current pipeline stage.",
            FORECAST_CLOSE_DATE="Expected close date of the opportunity.",
            ACTUAL_CLOSE_DATE="Date the opportunity was actually closed.",
        ),
    },
    "Leads": {
        "description": "Unqualified prospects that can be converted into contacts, organisations, and opportunities.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            LEAD_ID="Unique identifier for the lead.",
            FIRST_NAME="Lead's first name.",
            LAST_NAME="Lead's last name.",
            EMAIL="Lead's email address.",
            ORGANISATION_NAME="Organisation the lead is associated with.",
            LEAD_STATUS_ID="ID of the lead's status.",
            LEAD_SOURCE_ID="ID of the lead's source.",
            CONVERTED="Whether the lead has been converted.",
            CONVERTED_DATE_UTC="UTC timestamp when the lead was converted.",
        ),
    },
    "Projects": {
        "description": "Projects used to manage post-sale work and deliverables.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            PROJECT_ID="Unique identifier for the project.",
            PROJECT_NAME="Name of the project.",
            STATUS="Current status of the project (e.g. NOT STARTED, IN PROGRESS, COMPLETED).",
            PIPELINE_ID="ID of the pipeline the project is in.",
            STAGE_ID="ID of the current pipeline stage.",
            COMPLETED_DATE_UTC="UTC timestamp when the project was completed.",
        ),
    },
    "Tasks": {
        "description": "To-do items assigned to users and linked to CRM records.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            TASK_ID="Unique identifier for the task.",
            TITLE="Title of the task.",
            STATUS="Current status of the task (e.g. NOT STARTED, IN PROGRESS, COMPLETED).",
            DUE_DATE="Due date of the task.",
            COMPLETED="Whether the task is complete.",
            COMPLETED_DATE_UTC="UTC timestamp when the task was completed.",
            PRIORITY="Priority of the task.",
            RESPONSIBLE_USER_ID="User ID of the person responsible for the task.",
        ),
    },
    "Events": {
        "description": "Calendar events and appointments.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            EVENT_ID="Unique identifier for the event.",
            TITLE="Title of the event.",
            LOCATION="Location of the event.",
            START_DATE_UTC="UTC start time of the event.",
            END_DATE_UTC="UTC end time of the event.",
            ALL_DAY="Whether the event lasts all day.",
        ),
    },
    "Notes": {
        "description": "Free-text notes attached to CRM records.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            NOTE_ID="Unique identifier for the note.",
            TITLE="Title of the note.",
            BODY="Body text of the note.",
        ),
    },
    "Emails": {
        "description": "Emails logged against CRM records.",
        "docs_url": _DOCS_URL,
        "columns": _columns(
            EMAIL_ID="Unique identifier for the email.",
            SUBJECT="Subject line of the email.",
            EMAIL_FROM="Sender of the email.",
            EMAIL_DATE_UTC="UTC timestamp when the email was sent.",
        ),
    },
    "Users": {
        "description": "Insightly users in your account.",
        "docs_url": _DOCS_URL,
        "columns": {
            "USER_ID": "Unique identifier for the user.",
            "FIRST_NAME": "User's first name.",
            "LAST_NAME": "User's last name.",
            "EMAIL_ADDRESS": "User's email address.",
            "ADMINISTRATOR": "Whether the user is an account administrator.",
            "ACTIVE": "Whether the user account is active.",
            "DATE_CREATED_UTC": "UTC timestamp when the user was created.",
            "DATE_UPDATED_UTC": "UTC timestamp when the user was last modified.",
        },
    },
    "Pipelines": {
        "description": "Sales/project pipelines used to organise opportunities and projects into stages.",
        "docs_url": _DOCS_URL,
        "columns": {
            "PIPELINE_ID": "Unique identifier for the pipeline.",
            "PIPELINE_NAME": "Name of the pipeline.",
            "FOR_OPPORTUNITIES": "Whether the pipeline applies to opportunities.",
            "FOR_PROJECTS": "Whether the pipeline applies to projects.",
        },
    },
}
