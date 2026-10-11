from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the official Elastic Email v4 API reference and SDK models. Keyed by the
# endpoint/schema name returned by `get_schemas`. Columns mirror the PascalCase JSON the API returns.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "Email contacts in the account, including their subscription status and custom fields.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Contacts",
        "columns": {
            "Email": "Contact's email address. Unique per account.",
            "Status": "Subscription status (e.g. Active, Bounced, Unsubscribed, Transactional).",
            "FirstName": "Contact's first name.",
            "LastName": "Contact's last name.",
            "CustomFields": "Key-value map of custom contact fields defined in the account.",
            "Source": "How the contact was added (e.g. DeliveryApi, ManualInput, FileUpload).",
            "DateAdded": "Date the contact was created, in YYYY-MM-DDThh:mm:ss format.",
            "DateUpdated": "Date the contact was last changed.",
            "StatusChangeDate": "Date of the contact's last status change.",
        },
    },
    "lists": {
        "description": "Contact lists used to group contacts for campaigns.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Lists",
        "columns": {
            "ListName": "Name of the list.",
            "PublicListID": "Public ID code of the list (distinct from the internal listid).",
            "DateAdded": "Date the list was created, in YYYY-MM-DDThh:mm:ss format.",
            "AllowUnsubscribe": "Whether contacts are allowed to unsubscribe from this list.",
        },
    },
    "segments": {
        "description": "Dynamic contact segments defined by a rule.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Segments",
        "columns": {
            "Name": "Segment name.",
            "Rule": "SQL-like rule that determines which contacts belong to this segment.",
        },
    },
    "campaigns": {
        "description": "Email campaigns configured in the account.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Campaigns",
        "columns": {
            "Name": "Campaign name.",
            "Status": "Current campaign status (e.g. Draft, Active, Completed, Paused).",
            "Content": "Campaign email content; multiple items indicate an A/X split campaign.",
            "Recipients": "Lists and segments the campaign is sent to.",
            "Options": "Send and scheduling options for the campaign.",
        },
    },
    "templates": {
        "description": "Reusable email templates (personal and global scope).",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Templates",
        "columns": {
            "Name": "Template name.",
            "TemplateType": "Template type (e.g. RawHTML, DragDropEditor).",
            "TemplateScope": "Template visibility: Personal or Global.",
            "Subject": "Default email subject for the template.",
            "DateAdded": "Date the template was created, in YYYY-MM-DDThh:mm:ss format.",
        },
    },
    "events": {
        "description": "Recipient-level email events (sends, opens, clicks, bounces, complaints, unsubscribes). Immutable; synced append-only.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Events",
        "columns": {
            "TransactionID": "ID of the transaction (send) this event belongs to.",
            "MsgID": "ID of the individual message this event belongs to.",
            "FromEmail": "From address of the email.",
            "To": "Recipient address of the email.",
            "Subject": "Subject of the email.",
            "EventType": "Type of event (Submission, Sent, Open, Click, Bounce, Complaint, Unsubscribe, FailedAttempt).",
            "EventDate": "Date the event occurred.",
            "ChannelName": "Name of the channel the email was sent through.",
            "MessageCategory": "Category of the message (e.g. Spam, BlackListed, NoMailbox, Unknown).",
            "Message": "Error message when sending failed (FailedAttempt or Bounce).",
            "IPAddress": "IP address the email was sent through.",
            "PoolName": "Name of the IP pool the email was sent through.",
        },
    },
    "suppressions": {
        "description": "Suppressed recipients (bounces, complaints, and unsubscribes) that are excluded from sends.",
        "docs_url": "https://elasticemail.com/developers/api-documentation/rest-api#tag/Suppressions",
        "columns": {
            "Email": "Suppressed email address.",
            "FriendlyErrorMessage": "Human-readable RFC error message for the suppression.",
            "ErrorCode": "SMTP error code associated with the suppression.",
            "DateUpdated": "Date the suppression was last changed.",
        },
    },
}
