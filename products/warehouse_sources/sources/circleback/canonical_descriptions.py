from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "meetings": {
        "description": "A meeting recorded by Circleback, with its notes, attendees, action items and insights.",
        "docs_url": "https://circleback.ai/docs/api/meetings/list-meetings",
        "columns": {
            "id": "Circleback meeting ID. The meeting opens at https://circleback.ai/meetings/{id}.",
            "name": "Meeting name.",
            "createdAt": "When the meeting was created, as an ISO 8601 timestamp.",
            "updatedAt": "When the meeting was last updated.",
            "duration": "Meeting duration in seconds.",
            "url": "URL of the virtual meeting (Zoom, Google Meet, or Microsoft Teams).",
            "recordingUrl": "URL of the meeting recording file. It is valid for 24 hours and is only set when saving recordings is enabled in Circleback.",
            "tags": "Tags added to the meeting.",
            "icalUid": "Unique identifier of the calendar event associated with the meeting.",
            "attendees": "Meeting attendees.",
            "notes": "Circleback meeting notes with Markdown formatting.",
            "actionItems": "Action items created for the meeting.",
            "insights": "Insight results for the meeting, keyed by the name of the user-created insight.",
            "linkAccess": "Who can access the meeting through its shareable link.",
            "sharedWith": "People, teams, and workspaces with access to the meeting.",
        },
    },
    "transcripts": {
        "description": "One segment of a meeting transcript, in chronological order within its meeting.",
        "docs_url": "https://circleback.ai/docs/api/meetings/get-meeting-transcript",
        "columns": {
            "meeting_id": "ID of the meeting the segment belongs to.",
            "speaker": "Speaker name.",
            "text": "Words spoken.",
            "timestamp": "Offset in seconds from the start of the meeting to the beginning of the segment.",
        },
    },
    "action_items": {
        "description": "An action item from a meeting, with its assignee and completion status.",
        "docs_url": "https://circleback.ai/docs/api/action-items/list-action-items",
        "columns": {
            "id": "The unique identifier of the action item.",
            "title": "The title of the action item.",
            "description": "The detailed description of the action item.",
            "assignee": "The person the action item is assigned to, or null if it is unassigned.",
            "status": "The completion status of the action item, PENDING or DONE.",
            "completedAt": "When the action item was marked as done, or null if it is not completed.",
            "meetingIds": "The IDs of the associated meetings that the API key's owner can access.",
            "meetings": "The associated meetings that the API key's owner can access.",
            "canEditActionItem": "Whether the API key's owner can edit the action item.",
        },
    },
    "people": {
        "description": "A person who attends meetings, ordered by their most recent meeting.",
        "docs_url": "https://circleback.ai/docs/api/people/list-people",
        "columns": {
            "id": "The unique identifier of the person.",
            "email": "The person's email address.",
            "firstName": "The person's first name.",
            "lastName": "The person's last name.",
            "title": "The person's job title.",
            "companyId": "The unique identifier of the company the person belongs to.",
            "companyName": "The name of the company the person belongs to.",
        },
    },
    "companies": {
        "description": "A company whose people attend meetings, identified by its website domain.",
        "docs_url": "https://circleback.ai/docs/api/companies/list-companies",
        "columns": {
            "domain": "The company's website domain.",
            "name": "The company's name.",
            "avatarUrl": "The URL of the company's logo image.",
        },
    },
    "tags": {
        "description": "A tag that can be added to meetings.",
        "docs_url": "https://circleback.ai/docs/api/tags/list-tags",
        "columns": {
            "id": "The unique identifier of the tag.",
            "name": "The display name of the tag.",
            "description": "A description of the tag.",
        },
    },
}
