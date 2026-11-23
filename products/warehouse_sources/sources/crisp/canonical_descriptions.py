from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "conversations": {
        "description": "Support conversations in the workspace, including conversations without messages.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-conversations",
        "columns": {
            "session_id": "The conversation identifier.",
            "people_id": "The identifier of the contact linked to the conversation.",
            "state": "The conversation state: pending, unresolved, or resolved.",
            "created_at": "The time when Crisp created the conversation.",
            "updated_at": "The time when Crisp last updated the conversation.",
        },
    },
    "messages": {
        "description": "Messages from each conversation, including operator notes and events.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#get-messages-in-conversation",
        "columns": {
            "session_id": "The conversation that contains the message.",
            "conversation_updated_at": "The time when Crisp last updated the conversation that contains the message.",
            "fingerprint": "The message identifier within the conversation.",
            "timestamp": "The time when Crisp sent the message.",
            "content": "The message text or structured content for other message types.",
            "edited": "Whether someone edited the message after sending it.",
        },
    },
    "people": {
        "description": "Contact profiles with personal information, company information, and segments.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-people-profiles",
        "columns": {
            "people_id": "The contact identifier.",
            "email": "The email address of the contact.",
            "person": "Personal information for the contact.",
            "company": "Company information for the contact.",
            "created_at": "The time when Crisp created the contact profile.",
        },
    },
    "people_events": {
        "description": "Events recorded for each contact profile.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-people-events",
        "columns": {
            "people_id": "The contact that owns the event.",
            "text": "The event text.",
            "data": "Additional data attached to the event.",
            "timestamp": "The time when Crisp recorded the event.",
        },
    },
    "operators": {
        "description": "Joined operators and plugin developers in the workspace. Pending invitations are excluded.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-website-operators",
        "columns": {
            "user_id": "The operator identifier.",
            "type": "The member type: operator or sandbox.",
            "role": "The operator role in the workspace.",
            "availability": "The availability of the operator.",
        },
    },
    "visitors": {
        "description": "Visitors on the website at the time of the sync. This table contains no visitor history.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-visitors",
        "columns": {
            "session_id": "The visitor session identifier.",
            "active": "Whether the visitor actively browses the website.",
            "last_page": "The last page that the visitor opened.",
        },
    },
    "helpdesk_locales": {
        "description": "Helpdesk locales with public URLs and content counts.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-helpdesk-locales",
        "columns": {
            "locale_id": "The locale identifier.",
            "locale": "The locale code in ISO 639-1 format.",
            "url": "The public helpdesk URL for the locale.",
        },
    },
    "helpdesk_articles": {
        "description": "Published article titles and URLs for each helpdesk locale. Article bodies and drafts are excluded.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-helpdesk-pages",
        "columns": {
            "locale": "The locale code of the helpdesk article.",
            "entity_id": "The article identifier within the locale.",
            "title": "The article title.",
            "url": "The public article URL.",
            "tree_path": "The content path in the helpdesk tree.",
        },
    },
    "conversation_events": {
        "description": "Events that an integration or operator stacked in each conversation.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-conversation-events",
        "columns": {
            "session_id": "The conversation that contains the event.",
            "text": "The event text.",
            "data": "The event data, if any.",
            "color": "The event color, if any.",
            "timestamp": "The time when the event was stacked.",
        },
    },
    "teams": {
        "description": "Operator teams in the workspace.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-teams",
        "columns": {
            "team_id": "The team identifier.",
            "name": "The team name.",
            "operators": "The user identifiers of the team operators.",
            "created_at": "The time when Crisp created the team.",
            "updated_at": "The time when Crisp last updated the team.",
        },
    },
    "inboxes": {
        "description": "Inboxes in the workspace, with their members and routing conditions.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-website-inboxes",
        "columns": {
            "inbox_id": "The inbox identifier.",
            "name": "The inbox name.",
            "order": "The position of the inbox in the inbox list.",
            "operators": "The user identifiers of the inbox members.",
            "teams": "The identifiers of the teams that are inbox members.",
            "team_operators": "The user identifiers of the operators in the member teams.",
            "conditions": "The conditions that route conversations to the inbox.",
            "created_at": "The time when Crisp created the inbox.",
            "updated_at": "The time when Crisp last updated the inbox.",
        },
    },
    "helpdesk_feedbacks": {
        "description": "Reader ratings and comments on helpdesk articles, for each helpdesk locale.",
        "docs_url": "https://docs.crisp.chat/references/rest-api/v1/#list-helpdesk-locale-feedbacks",
        "columns": {
            "locale": "The locale code of the rated article.",
            "rating": "The rating: helpful or unhelpful.",
            "comment": "The comment that the reader left, if any.",
            "article": "The rated article, with its identifier, title, and URL.",
            "session": "The reader that left the feedback, if known.",
            "created_at": "The time when the reader left the feedback.",
        },
    },
}
