from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Table and column descriptions taken from the official Flexmail API reference
# (https://api.flexmail.eu/documentation/).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A contact in your Flexmail account, with their email address, name, language, and custom field values.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/contacts",
        "columns": {
            "id": "Unique identifier of the contact.",
            "email": "The contact's email address.",
            "first_name": "The contact's first name.",
            "name": "The contact's last name.",
            "language": "The language the contact wants to receive emails in.",
            "custom_fields": "The contact's values for the account's custom fields, keyed by custom field placeholder.",
        },
    },
    "custom_fields": {
        "description": "A custom field configured for contacts in your Flexmail account (free text, multiple choice, numeric, or date).",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/custom-fields",
        "columns": {
            "id": "Unique identifier of the custom field.",
            "type": "The type of the custom field: free_text, multiple_choice, numeric, or date.",
            "placeholder": "The placeholder used to reference the custom field in messages and contact payloads.",
            "name": "The display name of the custom field.",
        },
    },
    "interests": {
        "description": "An interest contacts can subscribe to, used to segment your audience by topic.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/interests",
        "columns": {
            "id": "Unique identifier of the interest.",
            "name": "The internal name of the interest as used in the Flexmail account.",
            "visibility": "Whether the interest is public (visible to contacts) or private.",
            "label": "How the interest is shown to your contacts.",
            "description": "An optional extra description shown to your contacts for context.",
        },
    },
    "opt_in_forms": {
        "description": "An active opt-in form contacts can use to subscribe to your communications.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/opt-in-forms",
        "columns": {
            "id": "Unique identifier of the opt-in form.",
            "name": "The display name of the opt-in form.",
            "language": "The language of the opt-in form.",
            "created_at": "The timestamp when the opt-in form was created.",
        },
    },
    "preferences": {
        "description": "A communication preference contacts can subscribe to, such as a newsletter.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/preferences",
        "columns": {
            "id": "Unique identifier of the preference.",
            "title": "How the preference is shown in the Flexmail UI to you.",
            "label": "How the preference is shown to your contacts.",
            "description": "An optional extra description shown to your contacts for context.",
        },
    },
    "segments": {
        "description": "An active segment: a saved set of conditions grouping contacts for targeting campaigns.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/segments",
        "columns": {
            "id": "Unique identifier of the segment.",
            "parent_id": "The identifier of the segment's parent. Absent if the segment has no parent.",
            "name": "A human readable name for the segment.",
            "number_of_contacts": "The number of contacts in this segment.",
            "last_campaign_date": "The date when a campaign was last sent to this segment. Absent if no campaign has ever been sent.",
        },
    },
    "sources": {
        "description": "A source describing where contacts originated, such as a signup form or import.",
        "docs_url": "https://api.flexmail.eu/documentation/#get-/sources",
        "columns": {
            "id": "Unique identifier of the source.",
            "name": "The name of the source.",
        },
    },
}
