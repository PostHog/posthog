from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "Users in the Frontegg environment, with account membership and profile details.",
        "docs_url": "https://developers.frontegg.com/ciam/api/identity/user-management/userscontrollerv3_getusers",
        "columns": {
            "id": "The user identifier.",
            "email": "The user's email address.",
            "createdAt": "The time when the user was created.",
            "lastLogin": "The time of the user's last login.",
        },
    },
    "roles": {
        "description": "Roles in the Frontegg environment, with their permissions and account scope.",
        "docs_url": "https://developers.frontegg.com/ciam/api/identity/account-roles/permissionscontrollerv2_getallroles",
        "columns": {
            "id": "The role identifier.",
            "tenantId": "The account identifier for the role.",
            "permissions": "The permissions assigned to the role.",
            "createdAt": "The time when the role was created.",
        },
    },
    "permissions": {
        "description": "Permissions configured for the Frontegg environment, with role and category associations.",
        "docs_url": "https://developers.frontegg.com/ciam/api/identity/permissions/permissionscontrollerv1_getallpermissions",
        "columns": {
            "id": "The permission identifier.",
            "key": "The permission key.",
            "roleIds": "The identifiers of roles that have this permission.",
            "categoryId": "The category identifier for the permission.",
            "createdAt": "The time when the permission was created.",
        },
    },
    "tenants": {
        "description": "Accounts (tenants) in the Frontegg environment, with their names and metadata.",
        "docs_url": "https://developers.frontegg.com/ciam/api/tenants/accounts/tenantcontrollerv2_gettenants",
        "columns": {
            "tenantId": "The account (tenant) identifier. Users reference it in tenantId and tenantIds.",
            "name": "The account name.",
            "metadata": "Custom metadata stored on the account.",
            "createdAt": "The time when the account was created.",
        },
    },
    "audits": {
        "description": "Audit log events in the Frontegg environment, such as logins and user or account changes.",
        "docs_url": "https://developers.frontegg.com/ciam/api/audits/main/auditscontroller_v2_getaudits",
        "columns": {
            "frontegg_id": "The audit event identifier.",
            "tenantId": "The account (tenant) identifier for the event.",
            "email": "The email address of the user who performed the action.",
            "action": "The action that the event records.",
            "severity": "The event severity: Info, Medium, High, Critical, or Error.",
            "createdAt": "The time when the event was created.",
        },
    },
}
