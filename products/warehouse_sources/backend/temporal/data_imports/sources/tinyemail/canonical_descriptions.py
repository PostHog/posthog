from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

TINYEMAIL_API_DOCS_URL = "https://docs.tinyemail.com/docs/tiny-email/tinyemail"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An email campaign, including its content, schedule, and delivery statistics.",
        "docs_url": TINYEMAIL_API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the campaign.",
            "campaign": "The campaign's name, subject line, and preview text.",
            "status": "Current status of the campaign (for example, draft, scheduled, or sent).",
            "senderId": "Identifier of the sender profile used for the campaign.",
            "contactIds": "Identifiers of the contact lists the campaign targets.",
            "schedule": "Scheduling details, including the date and time the campaign is set to send.",
            "template": "The campaign's email template, including the rendered HTML.",
            "requests": "Number of send requests issued for the campaign.",
            "sent": "Number of emails sent.",
            "delivered": "Number of emails delivered.",
            "open": "Number of unique opens.",
            "totalOpen": "Total number of opens, including repeats.",
            "clicked": "Number of unique clicks.",
            "totalClicked": "Total number of clicks, including repeats.",
            "bounced": "Number of emails that bounced.",
            "spam": "Number of spam complaints.",
            "unsubscribed": "Number of recipients who unsubscribed.",
        },
    },
    "contacts": {
        "description": "A contact list (audience) that campaigns can be sent to.",
        "docs_url": TINYEMAIL_API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the contact list.",
            "name": "Name of the contact list.",
            "numberOfMembers": "Number of members in the contact list.",
        },
    },
    "contact_members": {
        "description": "A subscriber within a contact list, with their profile fields and tags.",
        "docs_url": TINYEMAIL_API_DOCS_URL,
        "columns": {
            "contact_id": "Identifier of the contact list this member belongs to.",
            "email": "The member's email address.",
            "firstName": "The member's first name.",
            "lastName": "The member's last name.",
            "company": "The member's company.",
            "address1": "First line of the member's address.",
            "address2": "Second line of the member's address.",
            "city": "The member's city.",
            "province": "The member's province or state.",
            "country": "The member's country.",
            "postalCode": "The member's postal code.",
            "birthday": "The member's birthday.",
            "currency": "The member's preferred currency.",
            "source": "Where the member was imported or captured from.",
            "tags": "Tags applied to the member.",
        },
    },
    "sender_details": {
        "description": "A sender profile (from name, email, and postal address) used to send campaigns.",
        "docs_url": TINYEMAIL_API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the sender profile.",
            "name": "The sender's from name.",
            "email": "The sender's from email address.",
            "emailConfirmed": "Whether the sender email address has been confirmed.",
            "dkimSigned": "Whether emails from this sender are DKIM signed.",
            "defaults": "Whether this is the default sender profile.",
            "address": "The sender's street address.",
            "city": "The sender's city.",
            "region": "The sender's region or state.",
            "country": "The sender's country.",
            "postalCode": "The sender's postal code.",
        },
    },
}
