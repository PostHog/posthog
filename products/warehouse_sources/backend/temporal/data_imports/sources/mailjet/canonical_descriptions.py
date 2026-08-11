"""Canonical, documentation-sourced descriptions for Mailjet endpoints and columns.

Sourced from the official Mailjet API reference (https://dev.mailjet.com/email/reference/).
Keyed by the resource names in `settings.py` `MAILJET_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mailjet table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contact": {
        "description": "A contact (recipient) stored in the Mailjet account.",
        "docs_url": "https://dev.mailjet.com/email/reference/contacts/contact/",
        "columns": {
            "ID": "Unique identifier for the contact.",
            "Email": "The contact's email address.",
            "Name": "The contact's name.",
            "IsExcludedFromCampaigns": "Whether the contact is excluded from all campaigns.",
            "IsOptInPending": "Whether the contact's opt-in confirmation is still pending.",
            "IsSpamComplaining": "Whether the contact has filed a spam complaint.",
            "CreatedAt": "Time the contact was created.",
            "LastActivityAt": "Time of the contact's last activity.",
            "LastUpdateAt": "Time the contact was last updated.",
            "DeliveredCount": "The number of messages successfully delivered to the contact.",
            "delivered_count": "The number of messages successfully delivered to the contact.",
        },
    },
    "contactslist": {
        "description": "A contact list in Mailjet that groups contacts for sending campaigns.",
        "docs_url": "https://dev.mailjet.com/email/reference/contacts/contact-list/",
        "columns": {
            "ID": "Unique identifier for the contact list.",
            "Name": "The name of the contact list.",
            "Address": "The internal sending address of the contact list.",
            "IsDeleted": "Whether the contact list has been deleted.",
            "SubscriberCount": "The number of subscribers in the contact list.",
            "CreatedAt": "Time the contact list was created.",
        },
    },
    "listrecipient": {
        "description": "The relationship linking a contact to a contact list, with its subscription status.",
        "docs_url": "https://dev.mailjet.com/email/reference/contacts/subscriptions/",
        "columns": {
            "ID": "Unique identifier for the list-recipient relationship.",
            "ContactID": "The identifier of the contact.",
            "ListID": "The identifier of the contact list.",
            "IsUnsubscribed": "Whether the contact has unsubscribed from the list.",
            "IsActive": "Whether the subscription is active.",
            "SubscribedAt": "Time the contact subscribed to the list.",
            "UnsubscribedAt": "Time the contact unsubscribed from the list, if applicable.",
            "list_name": "The name of the contact list the subscription belongs to.",
        },
    },
    "campaign": {
        "description": "A sent campaign in Mailjet representing a batch of messages.",
        "docs_url": "https://dev.mailjet.com/email/reference/campaigns/",
        "columns": {
            "ID": "Unique identifier for the campaign.",
            "Subject": "The subject line of the campaign.",
            "ListID": "The identifier of the contact list the campaign was sent to.",
            "Status": "The status of the campaign.",
            "CreatedAt": "Time the campaign was created.",
            "SendStartAt": "Time the campaign started sending.",
            "SendEndAt": "Time the campaign finished sending.",
            "IsDeleted": "Whether the campaign has been deleted.",
            "IsStarred": "Whether the campaign has been starred.",
        },
    },
    "campaigndraft": {
        "description": "A draft campaign in Mailjet, including its content and recipient configuration.",
        "docs_url": "https://dev.mailjet.com/email/reference/campaigns/campaign-draft/",
        "columns": {
            "ID": "Unique identifier for the campaign draft.",
            "Title": "The internal title of the campaign draft.",
            "Subject": "The subject line of the campaign draft.",
            "ContactsListID": "The identifier of the contact list targeted by the draft.",
            "Status": "The status of the campaign draft (e.g. draft, programmed, sent).",
            "SenderEmail": "The sender email address for the draft.",
            "CreatedAt": "Time the campaign draft was created.",
            "ModifiedAt": "Time the campaign draft was last modified.",
        },
    },
    "message": {
        "description": "An individual message (email) processed by Mailjet, with its delivery status.",
        "docs_url": "https://dev.mailjet.com/email/reference/messages/",
        "columns": {
            "ID": "Unique identifier for the message.",
            "ContactID": "The identifier of the recipient contact.",
            "CampaignID": "The identifier of the campaign the message belongs to.",
            "Status": "The delivery status of the message (sent, opened, clicked, bounced, etc.).",
            "ArrivedAt": "Time the message was delivered.",
            "Delay": "The delay before the message was sent.",
            "MessageSize": "The size of the message in bytes.",
            "SpamassassinScore": "The SpamAssassin score assigned to the message.",
            "IsOpenTracked": "Whether open tracking is enabled for the message.",
            "IsClickTracked": "Whether click tracking is enabled for the message.",
            "attachment_count": "The number of attachments included in the message.",
            "is_html_part_included": "Whether the message included an HTML part.",
        },
    },
    "contactmetadata": {
        "description": "A custom contact property (metadata field) definition in Mailjet.",
        "docs_url": "https://dev.mailjet.com/email/reference/contacts/contact-properties/",
        "columns": {
            "ID": "Unique identifier for the contact metadata field.",
            "Name": "The name of the metadata field.",
            "Datatype": "The data type of the field (str, int, float, bool, datetime).",
            "NameSpace": "The namespace of the metadata field (static or historic).",
        },
    },
    "template": {
        "description": "A reusable email template stored in the Mailjet account.",
        "docs_url": "https://dev.mailjet.com/email/reference/templates/",
        "columns": {
            "ID": "Unique identifier for the template.",
            "Name": "The name of the template.",
            "name": "The name of the template.",
            "Author": "The author of the template.",
            "Purposes": "The intended purposes of the template (marketing, transactional, automation).",
            "OwnerType": "The ownership type of the template (user, global, apikey).",
            "CreatedAt": "Time the template was created.",
        },
    },
    "openinformation": {
        "description": "An open event recording that a recipient opened a message in Mailjet.",
        "docs_url": "https://dev.mailjet.com/email/reference/messages/#v3_get_openinformation",
        "columns": {
            "ID": "Unique identifier for the open event.",
            "ContactID": "The identifier of the recipient contact who opened the message.",
            "MessageID": "The identifier of the message that was opened.",
            "CampaignID": "The identifier of the campaign the message belongs to.",
            "OpenedAt": "Time the message was opened.",
            "UserAgent": "The user agent of the device that opened the message.",
        },
    },
    "clickstatistics": {
        "description": "A click event recording that a recipient clicked a link in a message in Mailjet.",
        "docs_url": "https://dev.mailjet.com/email/reference/messages/#v3_get_clickstatistics",
        "columns": {
            "ID": "Unique identifier for the click event.",
            "ContactID": "The identifier of the recipient contact who clicked.",
            "MessageID": "The identifier of the message that contained the link.",
            "CampaignID": "The identifier of the campaign the message belongs to.",
            "Url": "The URL that was clicked.",
            "ClickedAt": "Time the link was clicked.",
            "UserAgent": "The user agent of the device that clicked the link.",
        },
    },
    "messageevent": {
        "description": (
            "A delivery or engagement event pushed by the Mailjet Event API: sent, open, click, "
            "bounce, blocked, spam or unsub. Mailjet has no list endpoint for this stream, so the "
            "table is populated by webhook deliveries only."
        ),
        "docs_url": "https://dev.mailjet.com/email/guides/webhooks/",
        "columns": {
            "event_id": "Identifier PostHog derives from the delivery body so repeated deliveries of the same event collapse onto one row.",
            "event": "The event type: sent, open, click, bounce, blocked, spam or unsub.",
            "time": "Unix timestamp of the event.",
            "email": "Email address of the recipient that triggered the event.",
            "mj_campaign_id": "The internal Mailjet campaign identifier for the message.",
            "mj_contact_id": "The internal Mailjet contact identifier for the recipient.",
            "customcampaign": "Value of the X-Mailjet-Campaign header, when one was provided at send time.",
            "MessageID": "The unique message identifier.",
            "Message_GUID": "The globally unique identifier for the message.",
            "CustomID": "The custom identifier provided at send time, if any.",
            "Payload": "The event payload provided at send time, if any.",
            "mj_message_id": "The unique message identifier as a string. Deprecated in favor of MessageID.",
            "smtp_reply": "The raw SMTP response message. Sent events only.",
            "ip": "IP address that triggered the event. Open, click and unsub events only.",
            "geo": "Country code of the IP address that triggered the event.",
            "agent": "User agent of the device that triggered the event.",
            "url": "The link that was clicked. Click events only.",
            "blocked": "Whether the bounce led to the recipient being blocked.",
            "hard_bounce": "Whether the delivery error was permanent.",
            "error_related_to": "The category the delivery error belongs to, such as recipient, domain or content.",
            "error": "The delivery error, such as user unknown or invalid domain.",
            "comment": "The raw SMTP error, including the reason for the bounce.",
            "source": "The feedback loop program that reported the spam complaint. Spam events only.",
            "mj_list_id": "The internal Mailjet contact list identifier. Unsub events only.",
        },
    },
}
