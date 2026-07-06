"""Canonical, documentation-sourced descriptions for Postmark endpoints and columns.

Sourced from the official Postmark API reference (https://postmarkapp.com/developer/api). Keyed by the
endpoint names in `settings.py` `POSTMARK_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Postmark table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "messages_outbound": {
        "description": "An outbound email message sent through Postmark.",
        "docs_url": "https://postmarkapp.com/developer/api/messages-api#outbound-messages",
        "columns": {
            "MessageID": "Unique identifier for the message.",
            "Status": "Delivery status of the message (e.g. sent, queued).",
            "From": "Sender email address.",
            "To": "Recipient email addresses.",
            "Cc": "Carbon-copy recipients.",
            "Bcc": "Blind carbon-copy recipients.",
            "Subject": "Subject line of the message.",
            "Tag": "Tag associated with the message for categorization.",
            "MessageStream": "The message stream the message was sent through.",
            "ReceivedAt": "Time at which Postmark received the message for sending.",
            "TrackOpens": "Whether open tracking is enabled for the message.",
            "TrackLinks": "Link-tracking mode for the message.",
            "Sandboxed": "Whether the message was sent in sandbox mode.",
        },
    },
    "messages_inbound": {
        "description": "An inbound email message received through Postmark.",
        "docs_url": "https://postmarkapp.com/developer/api/messages-api#inbound-messages",
        "columns": {
            "MessageID": "Unique identifier for the message.",
            "Status": "Processing status of the inbound message.",
            "From": "Sender email address.",
            "FromName": "Display name of the sender.",
            "To": "Recipient email addresses.",
            "Cc": "Carbon-copy recipients.",
            "Bcc": "Blind carbon-copy recipients.",
            "Subject": "Subject line of the message.",
            "MailboxHash": "Mailbox hash parsed from the recipient address.",
            "Tag": "Tag associated with the message.",
            "MessageStream": "The inbound message stream that received the message.",
            "ReceivedAt": "Time at which Postmark received the inbound message.",
        },
    },
    "bounces": {
        "description": "A bounce record for an email that could not be delivered.",
        "docs_url": "https://postmarkapp.com/developer/api/bounce-api",
        "columns": {
            "ID": "Unique identifier for the bounce.",
            "Type": "Type of bounce (e.g. HardBounce, SoftBounce, SpamComplaint).",
            "TypeCode": "Numeric code describing the bounce type.",
            "Name": "Human-readable name of the bounce type.",
            "Email": "Email address that bounced.",
            "From": "Sender address of the message that bounced.",
            "Tag": "Tag of the message that bounced.",
            "MessageID": "ID of the message that bounced.",
            "MessageStream": "Message stream the bounced message belonged to.",
            "ServerID": "ID of the Postmark server that recorded the bounce.",
            "Description": "Description of why the message bounced.",
            "Details": "Detailed bounce reason from the receiving server.",
            "BouncedAt": "Time at which the bounce occurred.",
            "DumpAvailable": "Whether a raw SMTP dump is available for the bounce.",
            "Inactive": "Whether the bounce caused the address to be deactivated.",
            "CanActivate": "Whether the bounced address can be reactivated.",
            "Subject": "Subject line of the message that bounced.",
        },
    },
    "templates": {
        "description": "An email template defined in Postmark.",
        "docs_url": "https://postmarkapp.com/developer/api/templates-api",
        "columns": {
            "TemplateId": "Unique identifier for the template.",
            "Name": "The template's name.",
            "Alias": "Alias used to reference the template when sending.",
            "Active": "Whether the template is active.",
            "TemplateType": "Type of template (Standard or Layout).",
            "LayoutTemplate": "Alias of the layout template this template uses, if any.",
        },
    },
    "message_streams": {
        "description": "A message stream that groups outbound or inbound messages in Postmark.",
        "docs_url": "https://postmarkapp.com/developer/api/message-streams-api",
        "columns": {
            "ID": "Unique identifier (alias) for the message stream.",
            "ServerID": "ID of the server the stream belongs to.",
            "Name": "The stream's name.",
            "Description": "Description of the stream.",
            "MessageStreamType": "Type of stream (Transactional, Broadcasts, or Inbound).",
            "CreatedAt": "Time at which the stream was created.",
            "UpdatedAt": "Time at which the stream was last updated.",
            "ArchivedAt": "Time at which the stream was archived, if applicable.",
        },
    },
}
