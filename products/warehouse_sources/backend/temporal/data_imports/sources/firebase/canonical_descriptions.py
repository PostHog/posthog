from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firebase.settings import AUTH_USERS_TABLE

# Only Firebase Auth has a fixed schema. Firestore collections and Realtime Database paths are
# shaped by the customer's own app, so their columns fall back to the LLM enrichment pass.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    AUTH_USERS_TABLE: {
        "description": "One row per Firebase Authentication account in the project. Password hashes and salts are never synced.",
        "docs_url": "https://cloud.google.com/identity-platform/docs/reference/rest/v1/projects.accounts/batchGet",
        "columns": {
            "localId": "Immutable unique ID of the account.",
            "email": "The account's email address.",
            "emailVerified": "Whether the account's email address has been verified.",
            "initialEmail": "The first email address associated with this account.",
            "displayName": "The display name of the account.",
            "photoUrl": "URL of the account's profile photo.",
            "phoneNumber": "The account's phone number.",
            "disabled": "Whether the account is disabled and blocked from signing in.",
            "createdAt": "Time the account was created, in milliseconds since epoch.",
            "lastLoginAt": "Last time the account signed in, in milliseconds since epoch.",
            "lastRefreshAt": "Timestamp when an ID token was last minted for this account.",
            "passwordUpdatedAt": "Time the account's password was last updated, in milliseconds since epoch.",
            "validSince": "Oldest timestamp, in seconds since epoch, at which an ID token is still considered valid.",
            "providerUserInfo": "JSON list of the identity providers linked to the account.",
            "mfaInfo": "JSON list of the multi-factor authentication providers enabled for the account.",
            "customAttributes": "JSON custom claims added to any ID token minted for the account.",
            "customAuth": "Whether the account has authenticated with a custom token.",
            "emailLinkSignin": "Whether the account can authenticate with an email link.",
            "tenantId": "ID of the Identity Platform tenant the account belongs to, when tenants are in use.",
            "version": "Version of the account's password.",
        },
    },
}
