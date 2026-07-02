from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from Concord's public API docs (https://api.doc.concordnow.com). Keyed by the
# endpoint names ConcordSource.get_schemas returns. Partial coverage is fine — anything omitted
# falls back to LLM enrichment.
_DOCS_URL = "https://api.doc.concordnow.com"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "organizations": {
        "description": "Organizations (companies/workspaces) the API key can access.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the organization.",
            "name": "Organization name.",
            "createdAt": "Creation date as a Unix timestamp in milliseconds.",
        },
    },
    "agreements": {
        "description": "Contracts and templates in the organization, with stage, parties, tags and key dates.",
        "docs_url": _DOCS_URL,
        "columns": {
            "uuid": "Unique agreement identifier (Concord agreement UID).",
            "title": "Agreement title.",
            "status": "Lifecycle stage (e.g. DRAFT, NEGOTIATION, SIGNING, CURRENT_CONTRACT, TRASHED).",
            "createdAt": "Creation date as a Unix timestamp in milliseconds.",
            "modifiedAt": "Last modification date as a Unix timestamp in milliseconds.",
            "createdBy": "User id of the creator.",
            "organizationId": "Id of the organization that owns the agreement.",
            "folderId": "Id of the folder containing the agreement.",
            "signatureDate": "Signature date as a Unix timestamp in milliseconds.",
            "endDate": "End/expiry date as a Unix timestamp in milliseconds.",
            "tags": "Tags applied to the agreement.",
            "parties": "Parties to the agreement.",
        },
    },
    "members": {
        "description": "Members of the organization, including their role and group memberships.",
        "docs_url": _DOCS_URL,
        "columns": {
            "userOrganizationId": "Stable identifier of the member within the organization (primary key).",
            "user": "The underlying user account.",
            "role": "The member's organization role.",
            "groups": "Groups the member belongs to.",
            "isActive": "Whether the member account is active.",
            "createdAt": "When the member joined, as a Unix timestamp in milliseconds.",
        },
    },
    "groups": {
        "description": "User groups (teams) defined in the organization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the group.",
            "name": "Group name.",
        },
    },
    "folders": {
        "description": "Folder tree of the organization, flattened to one row per folder.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the folder.",
            "name": "Folder name.",
            "parentId": "Id of the parent folder (null for the root).",
            "documentCount": "Number of documents in the folder.",
        },
    },
    "clauses": {
        "description": "Active clauses in the organization's clause library.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the clause.",
            "title": "Clause title.",
            "createdAt": "Creation date as a Unix timestamp in milliseconds.",
        },
    },
    "tags": {
        "description": "Tags defined in the organization for classifying agreements.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the tag.",
            "name": "Tag name.",
        },
    },
    "reports": {
        "description": "Saved reports in the organization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the report.",
            "name": "Report name.",
            "lastUpdatedAt": "Last modification date as a Unix timestamp in milliseconds.",
        },
    },
    "approvals": {
        "description": "Company-level approval workflows configured in the organization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the approval.",
        },
    },
    "events": {
        "description": "Organization audit log of lifecycle actions. Requires the Administrator role.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the event.",
            "createdAt": "When the event occurred, as a Unix timestamp in milliseconds.",
            "type": "Event type (e.g. AGREEMENT_CREATE, AGREEMENT_SIGN, ORGANIZATION_ADD_USER).",
            "actor": "The user or system that triggered the event.",
            "event": "The object the event relates to (e.g. the agreement).",
        },
    },
}
