from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://developer.mixmax.com/reference"

# Curated from the public Mixmax API docs (https://developer.mixmax.com). Keyed by the schema/endpoint
# name from `settings.ENDPOINTS`. Partial coverage is fine — anything missing falls back to LLM
# enrichment. Mixmax objects are MongoDB documents, so the identifier column is `_id` everywhere
# except live feed rows, which use `uid`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sequences": {
        "description": "Automated multi-step outreach sequences the API token's user can access.",
        "docs_url": f"{_DOCS}/sequences",
        "columns": {
            "_id": "Unique identifier for the sequence.",
            "name": "Human-readable name of the sequence.",
        },
    },
    "sequence_recipients": {
        "description": "Recipients added to each sequence, with their state and per-stage activity. Recipients still in a draft are not listed.",
        "docs_url": f"{_DOCS}/sequencesidrecipients",
        "columns": {
            "_id": "Identifier of the recipient.",
            "sequence_id": "Identifier of the sequence the recipient belongs to.",
            "sequenceId": "Identifier of the sequence the recipient belongs to.",
            "userId": "Identifier of the user who added the recipient.",
            "to": "The recipient's email address and name.",
            "state": "Recipient state, for example 'active', 'paused', 'completed' or 'failed'.",
            "completedReason": "Why the recipient left the sequence, for example 'exhausted', 'manuallyCancelled', 'unsubscribed' or 'bounced'. May be null.",
            "createdAt": "When the recipient was added, in Unix seconds.",
            "lastStageSentOrdinal": "Position of the last stage sent, counting from 1.",
            "analytics": "Open, click, and download totals across all stages.",
            "stages": "Each stage as it applies to this recipient: state, schedule and send times (Unix milliseconds), and engagement counts.",
        },
    },
    "sequence_folders": {
        "description": "Folders used to organize sequences.",
        "docs_url": f"{_DOCS}/sequence-folders",
        "columns": {
            "_id": "Unique identifier for the sequence folder.",
            "name": "Name of the folder.",
        },
    },
    "messages": {
        "description": "Tracked email messages sent through Mixmax.",
        "docs_url": f"{_DOCS}/messages",
        "columns": {
            "_id": "Unique identifier for the message.",
            "subject": "Subject line of the message.",
        },
    },
    "rules": {
        "description": "Automation rules that trigger Mixmax actions.",
        "docs_url": f"{_DOCS}/rules",
        "columns": {"_id": "Unique identifier for the rule."},
    },
    "code_snippets": {
        "description": "Reusable code snippets injected into emails.",
        "docs_url": f"{_DOCS}/code-snippets",
        "columns": {"_id": "Unique identifier for the code snippet."},
    },
    "snippet_tags": {
        "description": "Tags used to categorize snippets.",
        "docs_url": f"{_DOCS}/snippet-tags",
        "columns": {
            "_id": "Unique identifier for the snippet tag.",
            "name": "Name of the tag.",
        },
    },
    "meeting_types": {
        "description": "Configured meeting/appointment types used for scheduling.",
        "docs_url": f"{_DOCS}/meeting-types",
        "columns": {"_id": "Unique identifier for the meeting type."},
    },
    "insights_reports": {
        "description": "Saved insights reports.",
        "docs_url": f"{_DOCS}/insights",
        "columns": {"_id": "Unique identifier for the report."},
    },
    "polls": {
        "description": "Polls embedded in Mixmax emails.",
        "docs_url": f"{_DOCS}/polls",
        "columns": {"_id": "Unique identifier for the poll."},
    },
    "file_requests": {
        "description": "File requests sent through Mixmax.",
        "docs_url": f"{_DOCS}/file-requests",
        "columns": {"_id": "Unique identifier for the file request."},
    },
    "live_feed": {
        "description": "Real-time email tracking events such as opens, clicks and downloads.",
        "docs_url": f"{_DOCS}/live-feed",
        "columns": {"uid": "Unique identifier for the live feed event."},
    },
    "live_feed_events": {
        "description": "Individual tracking events (opens, clicks, downloads, replies) for each live feed message, up to 200 per message.",
        "docs_url": f"{_DOCS}/livefeedevents",
        "columns": {
            "_id": "Unique identifier for the event.",
            "message_id": "Identifier of the live feed message the event belongs to.",
            "type": "The type of event, such as 'opened' or 'replied'.",
            "timestamp": "When the event occurred, in milliseconds since the Unix epoch.",
            "recipientEmail": "Email address of the recipient who triggered the event.",
            "recipientName": "Name of the recipient who triggered the event.",
            "country": "Approximate country where the event occurred. May be null.",
            "region": "Approximate region, state or province where the event occurred. May be null.",
            "city": "Approximate city where the event occurred. May be null.",
            "os": "Operating system the event was triggered from. May be null.",
            "program": "Program or email client the event was triggered from. May be null.",
            "isMobile": "Whether the event was triggered from a mobile device. Approximate. May be null.",
            "linkUrl": "URL of the clicked link. Only present for 'clicked' events.",
            "linkText": "Text of the clicked link. Only present for 'clicked' events.",
            "fileName": "Name of the downloaded file. Only present for 'downloaded' events.",
        },
    },
    "teams": {
        "description": "Teams the API token's user is an accepted member of. Workspace admins also see every team in their workspace.",
        "docs_url": f"{_DOCS}/teams-1",
        "columns": {
            "_id": "Identifier of the team.",
            "name": "Name of the team.",
            "createdAt": "When the team was created.",
            "modifiedAt": "When the team was created or last renamed.",
        },
    },
    "team_members": {
        "description": "Members of each team, including pending invites.",
        "docs_url": f"{_DOCS}/teams-members-get",
        "columns": {
            "team_id": "Identifier of the team.",
            "memberId": "Identifier of the member on this team.",
            "userId": "The member's Mixmax user id. Missing for invitees who are not Mixmax users yet.",
            "email": "The member's email address.",
            "name": "The member's name, for members who are Mixmax users.",
            "role": "The member's role on the team: 'admin' or 'member'.",
            "accepted": "True once the invite is accepted, false if it was declined. Missing while the invite is pending.",
            "acceptedAt": "When the member accepted or declined the invite.",
            "createdAt": "When the member was first added.",
            "invitedAt": "When the invite was last sent.",
        },
    },
    "unsubscribes": {
        "description": "Addresses on the user's unsubscribe list, or the workspace's list when the user belongs to a workspace. Sequences do not send to these addresses.",
        "docs_url": f"{_DOCS}/unsubscribes-get",
        "columns": {
            "_id": "Identifier of the unsubscribe record.",
            "email": "The unsubscribed address, in lowercase.",
            "name": "The contact's name, if one was given.",
            "userId": "Identifier of the user who added the record, or whose message the contact unsubscribed from.",
            "orgId": "Identifier of the workspace, when the record belongs to a workspace.",
            "messageId": "The message the contact unsubscribed from, if any.",
            "sequenceId": "The sequence the contact unsubscribed from, if any.",
            "createdAt": "When the record was added.",
        },
    },
    "appointment_links": {
        "description": "The authenticated user's appointment (scheduling) links.",
        "docs_url": f"{_DOCS}/appointment-links",
        "columns": {
            "_id": "Unique identifier for the appointment link.",
            "userId": "Identifier of the user the appointment links belong to.",
        },
    },
    "users": {
        "description": "The authenticated Mixmax user's profile.",
        "docs_url": f"{_DOCS}/users",
        "columns": {
            "_id": "Unique identifier for the user.",
            "email": "The user's email address.",
        },
    },
    "user_preferences": {
        "description": "The authenticated user's Mixmax preferences.",
        "docs_url": f"{_DOCS}/user-preferences",
        "columns": {"_id": "Unique identifier for the preferences document."},
    },
}
