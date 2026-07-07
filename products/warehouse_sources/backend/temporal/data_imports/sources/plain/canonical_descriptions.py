"""Canonical, documentation-sourced descriptions for Plain endpoints and columns.

Sourced from the official Plain API reference (https://www.plain.com/docs/api-reference/graphql) and
the GraphQL queries in `queries.py`. Keyed by the endpoint names in `settings.py` `PLAIN_ENDPOINTS`,
which match the `ExternalDataSchema.name` of a synced Plain table. Columns absent here fall back to
LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A customer in Plain — a person who contacts your support team.",
        "docs_url": "https://www.plain.com/docs/api-reference/graphql/customers/queries/customers",
        "columns": {
            "id": "Unique identifier for the customer.",
            "externalId": "Your own identifier for the customer, set when the customer was created.",
            "fullName": "The customer's full name.",
            "shortName": "The customer's short or display name.",
            "email": "The customer's email address and whether it has been verified.",
            "status": "The customer's current status.",
            "statusChangedAt": "Time at which the customer's status last changed.",
            "assignedToUser": "The user the customer is assigned to, if any.",
            "company": "The company the customer belongs to, if any.",
            "marked_as_spam_at": "Time at which the customer was marked as spam, if applicable.",
            "createdAt": "Time at which the customer was created.",
            "createdBy": "The actor (user, machine user, or system) that created the customer.",
            "updatedAt": "Time at which the customer was last updated.",
            "updatedBy": "The actor that last updated the customer.",
        },
    },
    "threads": {
        "description": "A support conversation (thread) between a customer and your team in Plain.",
        "docs_url": "https://www.plain.com/docs/api-reference/graphql/threads/queries/threads",
        "columns": {
            "id": "Unique identifier for the thread.",
            "externalId": "Your own identifier for the thread, if set.",
            "customer": "The customer the thread belongs to.",
            "title": "The thread's title.",
            "previewText": "A short preview of the latest message in the thread.",
            "priority": "Priority of the thread (0 = urgent through 3 = low).",
            "status": "Current status of the thread (e.g. todo, snoozed, done).",
            "statusChangedAt": "Time at which the thread's status last changed.",
            "statusChangedBy": "The actor that last changed the thread's status.",
            "assignedToUser": "The user or machine user the thread is assigned to.",
            "labels": "Labels applied to the thread.",
            "supportEmailAddresses": "Support email addresses associated with the thread.",
            "firstInboundMessageInfo": "Information about the first inbound message in the thread.",
            "firstOutboundMessageInfo": "Information about the first outbound message in the thread.",
            "lastInboundMessageInfo": "Information about the most recent inbound message in the thread.",
            "lastOutboundMessageInfo": "Information about the most recent outbound message in the thread.",
            "createdAt": "Time at which the thread was created.",
            "createdBy": "The actor that created the thread.",
            "updatedAt": "Time at which the thread was last updated.",
            "updatedBy": "The actor that last updated the thread.",
        },
    },
    "timeline_entries": {
        "description": "An event on a thread's timeline in Plain — a chat, email, or note entry.",
        "docs_url": "https://www.plain.com/docs/api-reference/graphql/threads/queries/thread",
        "columns": {
            "id": "Unique identifier for the timeline entry.",
            "timestamp": "Time at which the timeline entry occurred.",
            "actor": "The actor (user, machine user, customer, or system) that created the entry.",
            "actor_type": "The kind of actor that created the entry (user, machine user, customer, or system).",
            "entry": "The entry's content, varying by type (chat, email, note, or custom).",
        },
    },
}
