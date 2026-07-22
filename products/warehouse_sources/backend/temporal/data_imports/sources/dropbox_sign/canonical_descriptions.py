"""Canonical, documentation-sourced descriptions for Dropbox Sign endpoints and columns.

Sourced from the official Dropbox Sign API reference (https://developers.hellosign.com/api/reference/).
Keyed by the endpoint names in `settings.py` `DROPBOX_SIGN_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Dropbox Sign table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "signature_requests": {
        "description": "A request sent to one or more signers to sign one or more documents.",
        "docs_url": "https://developers.hellosign.com/api/reference/operation/signatureRequestList/",
        "columns": {
            "signature_request_id": "Unique identifier for the signature request.",
            "title": "The title the signers see when reviewing the request.",
            "original_title": "The title used when the request was originally created.",
            "subject": "The subject line of the request email.",
            "message": "The message included with the request email.",
            "is_complete": "Whether all signers have signed the request.",
            "is_declined": "Whether any signer has declined the request.",
            "has_error": "Whether an error occurred during the signing process.",
            "test_mode": "Whether the request was created in test mode.",
            "requester_email_address": "Email address of the account that sent the request.",
            "signing_url": "URL where the request can be signed (embedded signing).",
            "details_url": "URL to view the request's details in Dropbox Sign.",
            "signatures": "The signers on the request and their signing status.",
            "cc_email_addresses": "Email addresses CC'd on the request.",
            "response_data": "Field values entered by signers on the documents.",
            "metadata": "Custom metadata attached to the request.",
            "created_at": "Unix timestamp at which the request was created.",
        },
    },
    "templates": {
        "description": "A reusable template that pre-defines documents, signer roles, and fields for signature requests.",
        "docs_url": "https://developers.hellosign.com/api/reference/operation/templateList/",
        "columns": {
            "template_id": "Unique identifier for the template.",
            "title": "The template's title.",
            "message": "The default message included with requests created from the template.",
            "is_creator": "Whether the connected account created the template.",
            "can_edit": "Whether the connected account can edit the template.",
            "is_locked": "Whether the template is locked from editing.",
            "is_embedded": "Whether the template is set up for embedded signing.",
            "signer_roles": "The signer roles defined on the template.",
            "cc_roles": "The CC roles defined on the template.",
            "documents": "The documents that make up the template.",
            "custom_fields": "Custom fields defined on the template.",
            "named_form_fields": "The form fields defined on the template's documents.",
            "accounts": "Accounts that have access to the template.",
            "metadata": "Custom metadata attached to the template.",
        },
    },
    "api_apps": {
        "description": "An API application registered under the account, used to embed Dropbox Sign and receive callbacks.",
        "docs_url": "https://developers.hellosign.com/api/reference/operation/apiAppList/",
        "columns": {
            "client_id": "Unique identifier (client id) for the API app.",
            "name": "The API app's name.",
            "domains": "The domains the API app is associated with.",
            "callback_url": "The URL events for this app are POSTed to.",
            "is_approved": "Whether the API app has been approved for production use.",
            "owner_account": "The account that owns the API app.",
            "options": "Configuration options for the API app.",
            "oauth": "OAuth settings for the API app.",
            "white_labeling_options": "White-labeling options applied to the API app.",
            "created_at": "Unix timestamp at which the API app was created.",
        },
    },
    "account": {
        "description": "The Dropbox Sign account connected via the API key.",
        "docs_url": "https://developers.hellosign.com/api/reference/operation/accountGet/",
        "columns": {
            "account_id": "Unique identifier for the account.",
            "email_address": "The account's email address.",
            "is_locked": "Whether the account is locked.",
            "is_paid_hs": "Whether the account has a paid Dropbox Sign subscription.",
            "is_paid_hf": "Whether the account has a paid HelloFax subscription.",
            "quotas": "The account's remaining API and signature-request quotas.",
            "callback_url": "The account-level callback URL events are POSTed to.",
            "role_code": "The account's role within its team.",
            "team_id": "Identifier of the team the account belongs to.",
            "locale": "The account's locale.",
        },
    },
}
