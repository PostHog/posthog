from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS_URL = "https://docs.helpin.ai/articles/rest-api-endpoints-and-scopes-223584da"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "support_conversations": {
        "description": "Support conversations in the Helpin inbox, from email, chat and other channels. Merged conversations and conversations that are snoozed at sync time are not listed.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the conversation.",
            "display_id": "Human-readable number of the conversation.",
            "mailbox_id": "Inbox (mailbox) that the conversation belongs to.",
            "subject": "Subject line of the conversation.",
            "status": "Status of the conversation: open, waiting_on_customer, resolved or spam.",
            "priority": "Priority of the conversation.",
            "channel": "Channel the conversation came in on, such as email or chat.",
            "customer_name": "Name of the customer.",
            "customer_email": "Email address of the customer.",
            "assigned_user_id": "Helpin user the conversation is assigned to.",
            "crm_contact_id": "CRM contact linked to the conversation.",
            "crm_company_id": "CRM company linked to the conversation.",
            "created_at": "Time the conversation was created.",
            "updated_at": "Time the conversation record was last changed.",
            "resolved_at": "Time the conversation was resolved.",
            "list_last_activity_at": "Time of the latest message, note or event in the conversation.",
        },
    },
    "support_conversation_messages": {
        "description": "Public messages in each support conversation, oldest first. Internal notes are not included.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the message.",
            "conversation_id": "Conversation the message belongs to.",
            "sender_type": "Who sent the message: customer, user, agent or ai.",
            "message_type": "Kind of message, such as a reply or a system event.",
            "content": "Text of the message.",
            "created_at": "Time the message was sent.",
        },
    },
    "support_inboxes": {
        "description": "Support inboxes: the shared inbox and each mailbox, with their conversation counts at sync time. At most 100 are listed.",
        "docs_url": _DOCS_URL,
    },
    "support_tags": {
        "description": "Tags for support conversations. At most 100 are listed.",
        "docs_url": _DOCS_URL,
    },
    "crm_contacts": {
        "description": "CRM contacts in the workspace, with their custom properties.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the contact.",
            "custom_properties": "Custom properties set on the contact.",
            "behavior": "Product usage of the contact, when product events are synced to Helpin.",
        },
    },
    "crm_companies": {
        "description": "CRM companies in the workspace, with their custom properties.",
        "docs_url": _DOCS_URL,
        "columns": {
            "company_id": "Unique identifier of the company.",
            "domain": "Web domain of the company.",
            "owner_member_id": "Workspace member who owns the company.",
            "updated_at": "Time the company was last changed.",
        },
    },
    "crm_deals": {
        "description": "CRM deals with their stage name and amount.",
        "docs_url": _DOCS_URL,
    },
    "crm_pipelines": {
        "description": "CRM deal pipelines with their ordered stages. At most 100 are listed.",
        "docs_url": _DOCS_URL,
    },
    "tasks": {
        "description": "Project tasks, including completed and archived tasks.",
        "docs_url": _DOCS_URL,
        "columns": {
            "task_id": "Unique identifier of the task.",
            "task_key": "Human-readable key of the task, such as ENG-42.",
            "state_id": "Workflow state the task is in.",
            "owner_member_ids": "Workspace members who own the task.",
            "updated_at": "Time the task was last changed.",
        },
    },
    "epics": {
        "description": "Epics with their state, owner, dates, health and progress counts.",
        "docs_url": _DOCS_URL,
    },
    "sprints": {
        "description": "Sprints with their dates, status and progress counts.",
        "docs_url": _DOCS_URL,
    },
    "objectives": {
        "description": "Objectives with their type, state, owners, linked epics and progress.",
        "docs_url": _DOCS_URL,
    },
    "labels": {
        "description": "Workspace and team labels for tasks, epics and objectives. Archived labels are not listed.",
        "docs_url": _DOCS_URL,
    },
    "workflows": {
        "description": "The workflow each team uses, with its ordered states. One row per team.",
        "docs_url": _DOCS_URL,
    },
    "teams": {
        "description": "Teams in the workspace.",
        "docs_url": _DOCS_URL,
    },
    "members": {
        "description": "Active workspace members with their role and teams. Email addresses are not included.",
        "docs_url": _DOCS_URL,
    },
    "documents": {
        "description": "Docs documents with their status, space and collection, including archived documents. The document body is not included.",
        "docs_url": _DOCS_URL,
    },
}
