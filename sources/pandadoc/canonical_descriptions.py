"""Canonical, documentation-sourced descriptions for PandaDoc endpoints and columns.

Sourced from the official PandaDoc API reference (https://developers.pandadoc.com/reference/about).
Keyed by the endpoint names in `settings.py` `PANDADOC_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced PandaDoc table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "documents": {
        "description": "A document in PandaDoc — a proposal, quote, or contract that can be sent and signed.",
        "docs_url": "https://developers.pandadoc.com/reference/list-documents",
        "columns": {
            "id": "Unique identifier for the document.",
            "name": "The document's name.",
            "status": "Current status of the document (e.g. document.draft, document.sent, document.completed).",
            "date_created": "Time at which the document was created.",
            "date_modified": "Time at which the document was last modified; an incremental cursor.",
            "date_completed": "Time at which the document was completed (signed by all parties), if applicable.",
            "expiration_date": "Time at which the document expires, if set.",
            "version": "Version number of the document.",
            "template_id": "ID of the template the document was created from, if any.",
            "created_by": "The user who created the document.",
            "metadata": "Custom key-value metadata attached to the document.",
            "tokens": "Token (variable) values populated in the document.",
            "fields": "Form fields defined on the document.",
            "recipients": "Recipients the document is shared with or sent to.",
            "grand_total": "Grand total amount for documents that contain pricing.",
        },
    },
    "templates": {
        "description": "A reusable template used to create documents with predefined content and fields.",
        "docs_url": "https://developers.pandadoc.com/reference/list-templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "The template's name.",
            "date_created": "Time at which the template was created.",
            "date_modified": "Time at which the template was last modified.",
            "version": "Version number of the template.",
        },
    },
    "forms": {
        "description": "A PandaDoc form that collects responses and can generate documents from submissions.",
        "docs_url": "https://developers.pandadoc.com/reference/list-forms",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The form's name.",
            "status": "Current status of the form (e.g. active, paused, draft).",
            "created_by": "The user who created the form.",
            "date_created": "Time at which the form was created.",
            "date_modified": "Time at which the form was last modified.",
        },
    },
    "contacts": {
        "description": "A contact stored in PandaDoc that can be added as a recipient on documents.",
        "docs_url": "https://developers.pandadoc.com/reference/contacts-list",
        "columns": {
            "id": "Unique identifier for the contact.",
            "email": "Contact's email address.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "company": "Contact's company name.",
            "job_title": "Contact's job title.",
            "phone": "Contact's phone number.",
            "state": "Contact's state/region.",
            "country": "Contact's country.",
            "city": "Contact's city.",
            "postal_code": "Contact's postal/ZIP code.",
        },
    },
    "members": {
        "description": "A member (user) of the PandaDoc workspace.",
        "docs_url": "https://developers.pandadoc.com/reference/members-list",
        "columns": {
            "user_id": "Unique identifier for the member.",
            "email": "Member's email address.",
            "first_name": "Member's first name.",
            "last_name": "Member's last name.",
            "is_active": "Whether the member's account is active.",
            "role": "The member's role in the workspace.",
            "date_created": "Time at which the member was added.",
            "date_modified": "Time at which the member was last modified.",
        },
    },
    "document_folders": {
        "description": "A folder used to organize documents in PandaDoc.",
        "docs_url": "https://developers.pandadoc.com/reference/list-document-folders",
        "columns": {
            "uuid": "Unique identifier for the folder.",
            "name": "The folder's name.",
            "date_created": "Time at which the folder was created.",
            "parent_uuid": "Identifier of the parent folder, if nested.",
        },
    },
    "template_folders": {
        "description": "A folder used to organize templates in PandaDoc.",
        "docs_url": "https://developers.pandadoc.com/reference/list-template-folders",
        "columns": {
            "uuid": "Unique identifier for the folder.",
            "name": "The folder's name.",
            "date_created": "Time at which the folder was created.",
            "parent_uuid": "Identifier of the parent folder, if nested.",
        },
    },
}
