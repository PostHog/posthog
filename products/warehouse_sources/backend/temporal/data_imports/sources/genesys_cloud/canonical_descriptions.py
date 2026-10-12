from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DETAILS_QUERY_DOCS_URL = "https://developer.genesys.cloud/analyticsdatamanagement/analytics/detail/conversation-query"

_CONVERSATION_COLUMNS = {
    "conversationId": "Unique identifier for the conversation.",
    "conversationStart": "The start time of the conversation.",
    "conversationEnd": "The end time of the conversation. Empty while the conversation is in progress.",
    "originatingDirection": "The original direction of the conversation (inbound or outbound).",
    "conversationInitiator": "Indicates the participant purpose of the participant initiating a message conversation.",
    "customerParticipation": "Indicates a messaging conversation in which the customer participated by sending at least one message.",
    "divisionIds": "Identifier(s) of division(s) associated with the conversation.",
    "externalTag": "External tag for the conversation.",
    "selfServed": "Indicates whether all flow sessions were self serviced.",
    "mediaStatsMinConversationMos": "The lowest estimated average MOS among all the audio streams belonging to this conversation.",
    "mediaStatsMinConversationRFactor": "The lowest R-factor value among all of the audio streams belonging to this conversation.",
    "evaluations": "Quality evaluations associated with this conversation.",
    "surveys": "Surveys associated with this conversation.",
    "resolutions": "Resolutions associated with this conversation.",
    "participants": "Participants in the conversation, each with their sessions, segments, and metrics.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "conversations": {
        "description": "Genesys Cloud conversations across all media types (voice, chat, email, messaging, callbacks), from the analytics conversation details query.",
        "docs_url": _DETAILS_QUERY_DOCS_URL,
        "columns": _CONVERSATION_COLUMNS,
    },
    "calls": {
        "description": "Genesys Cloud voice conversations (phone calls), from the analytics conversation details query.",
        "docs_url": _DETAILS_QUERY_DOCS_URL,
        "columns": _CONVERSATION_COLUMNS,
    },
    "participants": {
        "description": "One row per participant in a Genesys Cloud conversation (customer, agent, IVR, ACD queue, and so on).",
        "docs_url": _DETAILS_QUERY_DOCS_URL,
        "columns": {
            "conversationId": "Identifier of the conversation this participant belongs to.",
            "conversationStart": "The start time of the conversation this participant belongs to.",
            "conversationEnd": "The end time of the conversation this participant belongs to.",
            "participantId": "Unique identifier for the participant.",
            "participantName": "A human readable name identifying the participant.",
            "purpose": "The participant's purpose, for example customer, agent, ivr, or acd.",
            "userId": "Unique identifier for the Genesys Cloud user, for agent participants.",
            "teamId": "The team ID the user is a member of.",
            "externalContactId": "External contact identifier.",
            "externalOrganizationId": "External organization identifier.",
            "flaggedReason": "Reason for which the participant flagged the conversation.",
            "screenRecording": "Flag determining if a screen recording was started or not.",
            "sessions": "List of sessions associated with this participant, with segments and metrics.",
        },
    },
    "users": {
        "description": "Users (agents and other staff) in the Genesys Cloud organization, including inactive and deleted users.",
        "docs_url": "https://developer.genesys.cloud/useragentman/users/",
        "columns": {
            "id": "The globally unique identifier for the user.",
            "name": "The user's name.",
            "email": "The user's email address.",
            "username": "The user's login name.",
            "state": "The current state for this user (active, inactive, or deleted).",
            "division": "The division to which this user belongs.",
            "team": "The team the user is a member of.",
            "dateLastLogin": "The last time the user logged in using username and password.",
        },
    },
    "queues": {
        "description": "ACD routing queues in the Genesys Cloud organization.",
        "docs_url": "https://developer.genesys.cloud/routing/routing/",
        "columns": {
            "id": "The globally unique identifier for the queue.",
            "name": "The queue name.",
            "description": "The queue description.",
            "division": "The division to which this queue belongs.",
            "dateCreated": "The date the queue was created.",
            "dateModified": "The date of the last modification to the queue.",
            "memberCount": "The total number of members in the queue.",
            "userMemberCount": "The number of user members (non-group members) in the queue.",
            "joinedMemberCount": "The number of joined members in the queue.",
            "mediaSettings": "The media settings for the queue.",
            "scoringMethod": "The scoring method for the queue.",
        },
    },
}
