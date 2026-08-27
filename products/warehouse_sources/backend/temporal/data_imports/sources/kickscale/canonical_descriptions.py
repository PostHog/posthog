from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_SWAGGER_URL = "https://api.kickscale.com/swagger"

# Meetings and calls share the same DTO shape (id, timestamps, participants, metrics, insights,
# CRM references, ...) apart from a few endpoint-specific fields (calls add caller/callee/
# direction; meetings add participantEmails/metadata).
_SHARED_COLUMNS = {
    "id": "Unique identifier for the record.",
    "createdAt": "When the record was created in Kickscale.",
    "updatedAt": "When the record was last updated in Kickscale.",
    "clientId": "Identifier of the Kickscale workspace (client) the record belongs to.",
    "name": "Display name of the meeting or call.",
    "date": "Start date and time of the meeting or call.",
    "summary": "AI-generated summary of the conversation.",
    "actionItems": "Action items extracted from the conversation.",
    "participants": "Transcript participants detected in the recording.",
    "userQuestions": "Questions asked by the Kickscale user during the conversation.",
    "duration": "Duration of the recording, in seconds.",
    "emailDraft": "AI-drafted follow-up email for the conversation.",
    "feedback": "Feedback given on the meeting type's scored criteria.",
    "metrics": "Talk-time and engagement metrics (speak ratio, questions, patience, words per minute, monologue).",
    "type": "Meeting type configuration applied to this record.",
    "insights": "AI-generated insights extracted from the conversation.",
    "language": "Detected language of the transcript.",
    "outcome": "Recorded outcome of the meeting or call.",
    "comments": "Comments left on the record by Kickscale users.",
    "rating": "Manual rating given to the record.",
    "user": "Kickscale user who owns the record.",
    "recordingRef": "Download URL for the recording. Only valid for 2 days.",
    "transcript": "Full transcript of the conversation. Only populated when `expand` includes `meeting_transcript`.",
    "crmReference": "Linked CRM record (deal, company, contact) this conversation is associated with.",
    "customerDomains": "Email domains of external participants, used to associate the record with a customer.",
    "businessEntities": "Deals and companies detected or linked to the record.",
    "recordingConsent": "Recording consent status captured for the conversation.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "meetings": {
        "description": "Analyzed video meetings (Zoom, Teams, Meet) recorded and transcribed by Kickscale.",
        "docs_url": _SWAGGER_URL,
        "columns": {
            **_SHARED_COLUMNS,
            "participantEmails": "Email addresses of all detected meeting participants.",
            "metadata": "User-provided metadata attached to the meeting.",
        },
    },
    "calls": {
        "description": "Analyzed phone/dialer calls (Aircall, RingCentral, Genesys, HubSpot Calling) recorded and transcribed by Kickscale.",
        "docs_url": _SWAGGER_URL,
        "columns": {
            **_SHARED_COLUMNS,
            "caller": "Party that placed the call.",
            "callee": "Party that received the call.",
            "direction": "Call direction: inbound or outbound.",
            "externalCallId": "Identifier of the call in the originating telephony/dialer system.",
        },
    },
}
