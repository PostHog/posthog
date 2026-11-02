"""Canonical, documentation-sourced descriptions for Smartwaiver endpoints and columns.

Sourced from the official Smartwaiver v4 API reference (https://api.smartwaiver.com/docs/v4).
Keyed by the endpoint names in `settings.py` `SMARTWAIVER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Smartwaiver table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "templates": {
        "description": "A waiver template in your Smartwaiver account — the reusable document participants sign.",
        "docs_url": "https://api.smartwaiver.com/docs/v4",
        "columns": {
            "templateId": "Unique identifier of the waiver template.",
            "title": "Title of the waiver template.",
            "publishedVersion": "Version number of the currently published template.",
            "publishedOn": "Time at which the current version of the template was published.",
            "webUrl": "URL where the template can be signed on the web.",
            "kioskUrl": "URL where the template can be signed in kiosk mode.",
            "vanityUrls": "Custom vanity URLs configured for this template.",
            "webhook": "Webhook configuration for this template (endpoint and email-validation requirement), if any.",
        },
    },
    "waivers": {
        "description": "A signed waiver submitted by a participant, with signer details and template metadata.",
        "docs_url": "https://api.smartwaiver.com/docs/v4",
        "columns": {
            "waiverId": "Unique identifier of the signed waiver.",
            "templateId": "Identifier of the waiver template that was signed.",
            "title": "Title of the waiver at the time of signing.",
            "createdOn": "Time at which the waiver was signed.",
            "expirationDate": "Date the waiver expires, if the template has an expiration configured.",
            "expired": "Whether the waiver has expired.",
            "verified": "Whether the signer's email address has been verified.",
            "kiosk": "Whether the waiver was signed at a kiosk.",
            "firstName": "First name of the first participant on the waiver.",
            "middleName": "Middle name of the first participant on the waiver.",
            "lastName": "Last name of the first participant on the waiver.",
            "dob": "Date of birth of the first participant (1800-01-01 if age is verified with a checkbox).",
            "isMinor": "Whether the first participant is a minor.",
            "autoTag": "Auto-tag value passed via the waiver URL, if any.",
            "tags": "Tags applied to the waiver.",
            "flags": "Flagged questions on the waiver (display text and reason).",
            "events": "Events attached to the waiver (only when requested with event data).",
        },
    },
    "checkins": {
        "description": "A participant check-in recorded against a signed waiver. One waiver can have multiple check-in records — one per signer.",
        "docs_url": "https://api.smartwaiver.com/docs/v4",
        "columns": {
            "checkinId": "Identifier of the check-in record.",
            "date": "Time at which the check-in happened.",
            "waiverId": "Identifier of the signed waiver the check-in belongs to.",
            "position": "Zero-based position of the participant on the waiver; -1 means the guardian.",
            "firstName": "First name of the checked-in participant.",
            "lastName": "Last name of the checked-in participant.",
            "isMinor": "Whether the checked-in participant is a minor.",
            "dateSigned": "Time at which the underlying waiver was signed.",
            "templateId": "Identifier of the waiver template the waiver was created from.",
        },
    },
}
