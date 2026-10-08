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
}
