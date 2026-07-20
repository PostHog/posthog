"""Canonical, documentation-sourced descriptions for Mailosaur endpoints and columns.

Sourced from the official Mailosaur API reference (https://mailosaur.com/docs/api/). Keyed by the
endpoint names in `settings.py` `MAILOSAUR_ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced Mailosaur table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "servers": {
        "description": "Virtual test inboxes (SMTP/SMS servers) on the Mailosaur account.",
        "docs_url": "https://mailosaur.com/docs/api/servers/",
        "columns": {
            "id": "Unique identifier for the server.",
            "name": "The name of the server.",
            "users": "Users with access to the server.",
            "messages": "The number of messages currently held by the server.",
        },
    },
    "messages": {
        "description": "Summaries of emails and SMS messages received by each server. The parent server id is injected as `server`.",
        "docs_url": "https://mailosaur.com/docs/api/messages/",
        "columns": {
            "id": "Unique identifier for the message.",
            "server": "Identifier of the server that received the message (injected during sync).",
            "received": "The datetime the message was received.",
            "type": "The type of message (e.g. Email or SMS).",
            "subject": "The message's subject line.",
            "from": "The sender(s) of the message, each with a name and email/phone.",
            "to": "The recipient(s) of the message, each with a name and email/phone.",
            "cc": "Carbon-copy recipients of the message.",
            "bcc": "Blind carbon-copy recipients of the message.",
        },
    },
    "usage_transactions": {
        "description": "The last 31 days of account transactional usage, one row per day.",
        "docs_url": "https://mailosaur.com/docs/api/usage/",
        "columns": {
            "timestamp": "The date of the usage record.",
            "email": "The number of emails received that day.",
            "sms": "The number of SMS messages received that day.",
            "previews": "The number of email previews generated that day.",
        },
    },
}
