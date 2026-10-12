from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "locks": {
        "description": "Doors controlled through Kisi, including their connection and lock status.",
        "docs_url": "https://api.getkisi.com/docs#tag/locks/GET/locks",
        "columns": {
            "id": "Unique lock identifier.",
            "name": "Lock name.",
            "place_id": "Identifier of the place that contains the lock.",
            "online": "Whether the lock is online.",
            "created_at": "Time when the lock was created.",
            "updated_at": "Time when the lock was last updated.",
        },
    },
    "places": {
        "description": "Physical locations managed through Kisi.",
        "docs_url": "https://api.getkisi.com/docs#tag/places/GET/places",
        "columns": {
            "id": "Unique place identifier.",
            "name": "Place name.",
            "created_at": "Time when the place was created.",
            "updated_at": "Time when the place was last updated.",
        },
    },
    "users": {
        "description": "Users visible to the connected Kisi account.",
        "docs_url": "https://api.getkisi.com/docs#tag/users/GET/users",
        "columns": {
            "id": "Unique user identifier.",
            "name": "User name.",
            "email": "User email address.",
            "created_at": "Time when the user was created.",
            "updated_at": "Time when the user was last updated.",
        },
    },
    "groups": {
        "description": "Groups that define shared access rights in Kisi.",
        "docs_url": "https://api.getkisi.com/docs#tag/groups/GET/groups",
        "columns": {
            "id": "Unique group identifier.",
            "name": "Group name.",
            "place_id": "Identifier of the place associated with the group.",
            "created_at": "Time when the group was created.",
            "updated_at": "Time when the group was last updated.",
        },
    },
    "role_assignments": {
        "description": "Assignments that grant Kisi roles to users, teams, or guests.",
        "docs_url": "https://api.getkisi.com/docs#tag/role-assignments/GET/role_assignments",
        "columns": {
            "id": "Unique role assignment identifier.",
            "role_id": "Identifier of the assigned role.",
            "created_at": "Time when the role assignment was created.",
            "updated_at": "Time when the role assignment was last updated.",
        },
    },
    "controllers": {
        "description": "Kisi controllers and their connection status.",
        "docs_url": "https://api.getkisi.com/docs#tag/controllers/GET/controllers",
        "columns": {
            "id": "Unique controller identifier.",
            "name": "Controller name.",
            "online": "Whether the controller is online.",
            "place_id": "Identifier of the place that contains the controller.",
            "created_at": "Time when the controller was created.",
            "updated_at": "Time when the controller was last updated.",
        },
    },
    "readers": {
        "description": "Kisi readers and their connection status.",
        "docs_url": "https://api.getkisi.com/docs#tag/readers/GET/readers",
        "columns": {
            "id": "Unique reader identifier.",
            "name": "Reader name.",
            "online": "Whether the reader is online.",
            "lock_id": "Identifier of the lock associated with the reader.",
            "place_id": "Identifier of the place that contains the reader.",
            "created_at": "Time when the reader was created.",
            "updated_at": "Time when the reader was last updated.",
        },
    },
}
