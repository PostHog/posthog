"""Canonical, documentation-sourced descriptions for Torii endpoints and columns.

Sourced from the public Torii API reference (https://developers.toriihq.com). Keyed by the
resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Torii table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Apps": {
        "description": "A SaaS application discovered in the organization by Torii, with ownership, usage, and vendor metadata.",
        "docs_url": "https://developers.toriihq.com/reference/getapps",
        "columns": {
            "id": "Unique identifier for the app.",
            "name": "Name of the application.",
            "primaryOwner": "The user primarily responsible for the app.",
            "appOwners": "All users assigned as owners of the app.",
            "state": "Lifecycle state of the app (e.g. active, deprecated).",
            "category": "Category Torii has classified the app under.",
            "url": "Homepage or login URL for the app.",
            "imageUrl": "URL of the app's logo.",
            "description": "Short description of the app.",
            "tags": "Tags applied to the app in Torii.",
            "score": "Torii's risk/adoption score for the app.",
            "isCustom": "Whether this is a custom (manually added) app rather than one from Torii's catalog.",
            "addedBy": "The user or source that added the app to Torii.",
            "creationTime": "Time the app record was created in Torii.",
            "isHidden": "Whether the app is hidden from the main app list.",
            "sources": "Data sources (e.g. SSO, expense feeds) that discovered this app.",
            "vendor": "The vendor/company that publishes the app.",
            "activeUsersCount": "Number of currently active users of the app.",
            "lastVisitTime": "Most recent time any user accessed the app.",
        },
    },
    "Users": {
        "description": "A user in the organization tracked by Torii, with role and app-access summary.",
        "docs_url": "https://developers.toriihq.com/reference/getusers",
        "columns": {
            "firstName": "User's first name.",
            "lastName": "User's last name.",
            "email": "User's primary email address.",
            "additionalEmails": "Other email addresses associated with the user.",
            "creationTime": "Time the user record was created in Torii.",
            "idRole": "Identifier of the user's assigned role.",
            "role": "Name of the user's assigned role.",
            "lifecycleStatus": "User's employment lifecycle status: active, offboarding, or offboarded.",
            "isDeletedInIdentitySources": "Whether the user has been removed from the organization's identity sources.",
            "isExternal": "Whether the user is external to the organization.",
            "activeAppsCount": "Number of apps this user is an active user of.",
        },
    },
    "Contracts": {
        "description": "A SaaS contract tracked in Torii, covering renewal and ownership details for an app.",
        "docs_url": "https://developers.toriihq.com/reference/getcontracts",
        "columns": {
            "id": "Unique identifier for the contract.",
            "idApp": "Identifier of the app this contract covers.",
            "name": "Name of the contract.",
            "owner": "The user responsible for the contract.",
            "status": "Current status of the contract.",
            "createdBy": "The user who created the contract record in Torii.",
        },
    },
    "Transactions": {
        "description": "A recognized, mapped expense transaction associated with a SaaS app.",
        "docs_url": "https://developers.toriihq.com/reference/gettransactions",
        "columns": {
            "id": "Unique identifier for the transaction.",
            "idApp": "Identifier of the app this transaction is mapped to.",
            "appName": "Name of the app this transaction is mapped to.",
            "idAppAccount": "Identifier of the specific app account/instance charged.",
            "appAccountName": "Name of the specific app account/instance charged.",
            "fileName": "Name of the source file the transaction was imported from.",
            "transactionDate": "Date the transaction occurred.",
            "amount": "Transaction amount, including original currency value and organization-currency converted value.",
            "source": "System or feed the transaction was sourced from (e.g. a card feed or expense tool).",
            "description": "Free-text description of the transaction.",
            "department": "Department the transaction is attributed to.",
            "domain": "Email or billing domain associated with the transaction.",
            "externalAccountId": "Identifier of the account in the external source system.",
            "externalAccountName": "Name of the account in the external source system.",
            "mappingStatus": "Whether the transaction has been mapped to an app, is unmapped, or archived.",
            "mappingLogic": "Explanation of how the transaction was matched to its app.",
            "reportedByFullName": "Full name of the person who reported/submitted the transaction, if applicable.",
            "idExternalTransaction": "Identifier of the transaction in the external source system.",
        },
    },
}
