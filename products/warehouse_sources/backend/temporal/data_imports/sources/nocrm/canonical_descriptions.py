from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the noCRM.io v2 API reference (https://www.nocrm.io/api). Partial coverage is
# fine — anything omitted falls back to LLM enrichment using the docs_url and column data types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "leads": {
        "description": "Sales leads (opportunities) tracked in noCRM.io, including their pipeline step, status and value.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the lead.",
            "title": "Title of the lead.",
            "description": "Free-text description of the lead.",
            "html_description": "HTML-rendered description of the lead.",
            "status": "Lead status: one of todo, standby, won, lost or cancelled.",
            "pipeline": "Name of the pipeline the lead belongs to.",
            "step": "Name of the current pipeline step.",
            "step_id": "Identifier of the current pipeline step.",
            "amount": "Monetary value of the lead.",
            "amount_percentage": "Weighted amount as a percentage.",
            "probalized_amount": "Amount weighted by win probability.",
            "probability": "Estimated win probability (percent).",
            "currency": "Currency code for the lead's amount.",
            "starred": "Whether the lead is starred/flagged.",
            "tags": "List of tags applied to the lead.",
            "created_from": "How the lead was created (e.g. manual, api, form).",
            "attachment_count": "Number of attachments on the lead.",
            "next_action_at": "Timestamp of the next scheduled action.",
            "remind_date": "Date of the next reminder.",
            "remind_time": "Time of the next reminder.",
            "estimated_closing_date": "Expected date the lead will close.",
            "closed_at": "Timestamp the lead was closed (won/lost/cancelled).",
            "created_at": "Timestamp the lead was created.",
            "updated_at": "Timestamp the lead was last updated.",
            "created_by_id": "Identifier of the user who created the lead.",
            "user_id": "Identifier of the user the lead is assigned to.",
            "client_folder_id": "Identifier of the client folder the lead belongs to.",
            "client_folder_name": "Name of the client folder the lead belongs to.",
            "team_id": "Identifier of the team the lead belongs to.",
            "team_name": "Name of the team the lead belongs to.",
        },
    },
    "activities": {
        "description": "Activity types configured for the account, used to categorise lead activity.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the activity type.",
            "name": "Name of the activity type.",
            "icon": "Icon associated with the activity type.",
            "color": "Colour associated with the activity type.",
            "kind": "Kind/category of the activity type.",
            "parent_id": "Identifier of the parent activity type, if any.",
            "is_disabled": "Whether the activity type is disabled.",
            "position": "Display order position.",
        },
    },
    "users": {
        "description": "Users belonging to the noCRM.io account.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "Email address of the user.",
            "team_id": "Identifier of the team the user belongs to.",
        },
    },
    "teams": {
        "description": "Teams configured in the noCRM.io account.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Name of the team.",
        },
    },
    "steps": {
        "description": "Pipeline steps (stages) a lead can move through.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the step.",
            "name": "Name of the step.",
        },
    },
    "pipelines": {
        "description": "Sales pipelines configured in the account.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the pipeline.",
            "name": "Name of the pipeline.",
        },
    },
    "client_folders": {
        "description": "Client folders that group leads by account/company.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the client folder.",
            "name": "Name of the client folder.",
        },
    },
    "categories": {
        "description": "Categories used to classify client folders.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "Name of the category.",
        },
    },
    "tags": {
        "description": "Predefined tags that can be applied to leads.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
        },
    },
    "fields": {
        "description": "Custom field definitions configured for leads and client folders.",
        "docs_url": "https://www.nocrm.io/api",
        "columns": {
            "id": "Unique identifier for the custom field.",
            "name": "Name of the custom field.",
            "type": "Data type of the custom field.",
        },
    },
}
