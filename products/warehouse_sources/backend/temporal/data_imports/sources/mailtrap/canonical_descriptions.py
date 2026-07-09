from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Mailtrap API docs (https://docs.mailtrap.io/developers).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "email_logs": {
        "description": "A sent email's delivery log entry, covering both the transactional and bulk sending streams.",
        "docs_url": "https://docs.mailtrap.io/developers/email-sending/email-logs",
        "columns": {
            "message_id": "The unique UUID of the sent message.",
            "status": "Delivery status of the message (delivered, not_delivered, enqueued, or opted_out).",
            "subject": "The email subject line.",
            "from": "The sender email address.",
            "to": "The recipient email address.",
            "sent_at": "When the message was sent.",
            "client_ip": "IP address of the client that submitted the message.",
            "category": "The sender-assigned category of the message.",
            "custom_variables": "Custom variables attached to the message at send time.",
            "sending_stream": "Which sending stream carried the message (transactional or bulk).",
            "domain_id": "The ID of the sending domain the message was sent from.",
            "template_id": "The ID of the email template used, if any.",
            "template_variables": "Template variables supplied at send time, if a template was used.",
            "opens_count": "Number of times the message was opened.",
            "clicks_count": "Number of link clicks recorded for the message.",
        },
    },
    "suppressions": {
        "description": "A suppressed recipient email address that will not receive emails from your account.",
        "docs_url": "https://docs.mailtrap.io/developers/email-sending/suppressions",
        "columns": {
            "id": "The unique UUID of the suppression.",
            "type": "Reason for the suppression (hard bounce, unsubscription, spam complaint, or manual import).",
            "created_at": "When the suppression was created.",
            "email": "The suppressed email address.",
            "sending_stream": "Which sending stream the suppression applies to (transactional, bulk, or any).",
            "domain_name": "The sending domain the suppression is associated with.",
            "message_bounce_category": "Bounce category of the message that triggered the suppression.",
            "message_category": "Sender-assigned category of the triggering message.",
            "message_client_ip": "IP address of the client that submitted the triggering message.",
            "message_created_at": "When the triggering message was created.",
            "message_esp_response": "The receiving email service provider's response for the triggering message.",
            "message_esp_server_type": "The receiving email service provider's server type.",
            "message_outgoing_ip": "The IP address the triggering message was sent from.",
            "message_recipient_mx_name": "The recipient's MX server name.",
            "message_sender_email": "Sender address of the triggering message.",
            "message_subject": "Subject of the triggering message.",
        },
    },
    "email_templates": {
        "description": "A reusable email template with dynamic content.",
        "docs_url": "https://docs.mailtrap.io/developers/templates/templates",
        "columns": {
            "id": "The unique ID of the template.",
            "uuid": "The UUID of the template, used when sending emails from it.",
            "name": "The template name.",
            "category": "The template category.",
            "subject": "The email subject line the template renders.",
            "body_text": "The plain-text body of the template.",
            "body_html": "The HTML body of the template.",
            "created_at": "When the template was created.",
            "updated_at": "When the template was last updated.",
        },
    },
    "contact_lists": {
        "description": "A named list used to group marketing contacts.",
        "docs_url": "https://docs.mailtrap.io/developers/promotional/contacts/contact-lists",
        "columns": {
            "id": "The unique ID of the contact list.",
            "name": "The contact list name.",
        },
    },
    "sending_domains": {
        "description": "A domain configured for sending emails, with its compliance and DNS verification state.",
        "docs_url": "https://docs.mailtrap.io/developers/email-sending/domains",
        "columns": {
            "id": "The unique ID of the sending domain.",
            "domain_name": "The domain name.",
            "demo": "Whether this is a Mailtrap-provided demo domain.",
            "compliance_status": "The domain's compliance verification status; it must be compliant before production sending.",
        },
    },
    "accounts": {
        "description": "A Mailtrap account the API token has access to.",
        "docs_url": "https://docs.mailtrap.io/developers/account-management/accounts",
        "columns": {
            "id": "The unique ID of the account.",
            "name": "The account name.",
            "access_levels": "The token's access levels on the account (1000 owner, 100 admin, 10 viewer).",
        },
    },
}
