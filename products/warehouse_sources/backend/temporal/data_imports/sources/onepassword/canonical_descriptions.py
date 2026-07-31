from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the official 1Password Events API reference:
# https://developer.1password.com/docs/events-api/reference
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sign_in_attempts": {
        "description": (
            "Attempts to sign in to a 1Password account: who attempted to sign in, from which client and "
            "IP address, when the attempt was made, and — for failed attempts — the cause of the failure."
        ),
        "docs_url": "https://developer.1password.com/docs/events-api/reference#post-apiv2signinattempts",
        "columns": {
            "uuid": "The UUID of the sign-in attempt event.",
            "session_uuid": "The UUID of the session that created the event.",
            "timestamp": "The date and time of the sign-in attempt, in RFC 3339 format.",
            "category": "The category of the sign-in attempt (e.g. success, credentials_failed, mfa_failed, firewall_failed).",
            "type": "The details of the sign-in attempt (e.g. credentials_ok, password_secret_bad, ip_blocked).",
            "country": "The ISO 3166 country code of the event's original IP address.",
            "details": "Additional information about the sign-in attempt, such as the value blocked by a firewall rule.",
            "target_user": "The user the sign-in attempt targeted (UUID, name, and email).",
            "client": "The client used for the sign-in attempt: app name and version, platform, OS, and IP address.",
            "location": "The geolocated city, region, country, latitude, and longitude of the attempt.",
            "account_uuid": "The UUID of the account the user attempted to sign in to.",
        },
    },
    "item_usages": {
        "description": (
            "Usage of items in shared vaults: which item was modified, accessed, or used, by whom, from "
            "which client and IP address, and the vault where the item is stored."
        ),
        "docs_url": "https://developer.1password.com/docs/events-api/reference#post-apiv2itemusages",
        "columns": {
            "uuid": "The UUID of the item usage event.",
            "timestamp": "The date and time the item was used, in RFC 3339 format.",
            "used_version": "The version of the item that was used.",
            "vault_uuid": "The UUID of the vault the item is stored in.",
            "item_uuid": "The UUID of the item that was used.",
            "user": "The user who used the item (UUID, name, and email).",
            "client": "The client used to access the item: app name and version, platform, OS, and IP address.",
            "location": "The geolocated city, region, country, latitude, and longitude of the usage.",
            "action": "The action performed on the item (e.g. fill, reveal, secure-copy, share, export).",
            "user_type": "The type of user (user, or external_user for MSP accounts).",
            "user_account_uuid": "The UUID of the account the user belongs to (MSP accounts).",
            "account_uuid": "The UUID of the account the item usage occurred in.",
        },
    },
    "audit_events": {
        "description": (
            "Administrative actions performed by team members within a 1Password account: when an action "
            "was performed and by whom, along with the type and object of the action."
        ),
        "docs_url": "https://developer.1password.com/docs/events-api/reference#post-apiv2auditevents",
        "columns": {
            "uuid": "The UUID of the audit event.",
            "timestamp": "The date and time the action was performed, in RFC 3339 format.",
            "actor_uuid": "The UUID of the user who performed the action.",
            "actor_details": "The user who performed the action (UUID, name, and email).",
            "actor_type": "The type of user who performed the action (user, or external_user for MSP accounts).",
            "actor_account_uuid": "The UUID of the account the actor belongs to.",
            "account_uuid": "The UUID of the account where the action was performed.",
            "action": "The type of action that was performed (e.g. create, delete, grant, revoke, suspend).",
            "object_type": "The type of object the action was performed on (e.g. account, device, user, gm for group membership).",
            "object_uuid": "The UUID of the object the action was performed on.",
            "aux_id": "An additional ID relevant to the action.",
            "aux_uuid": "An additional UUID relevant to the action, such as the user a group membership change targeted.",
            "aux_details": "Additional details about the object of the action, such as the affected user.",
            "aux_info": "Additional information about the action, such as the role granted.",
            "session": "The session that created the event: UUID, login time, device UUID, and IP address.",
            "location": "The geolocated city, region, country, latitude, and longitude of the action.",
        },
    },
}
