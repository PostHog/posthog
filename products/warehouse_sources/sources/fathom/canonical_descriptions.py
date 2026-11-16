from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_LIST_MEETINGS_DOCS = "https://developers.fathom.ai/api-reference/meetings/list-meetings"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "meetings": {
        "description": (
            "A meeting that Fathom recorded, with its calendar details, attendees, action items, "
            "highlights and CRM matches. Only meetings the API key can view are included."
        ),
        "docs_url": _LIST_MEETINGS_DOCS,
        "columns": {
            "recording_id": "The ID of the meeting recording.",
            "title": "The title of the meeting in Fathom.",
            "meeting_title": "The title of the calendar event.",
            "meeting_type": "The name of the meeting type assigned to the meeting, or null if none is assigned.",
            "url": "The URL of the meeting in Fathom.",
            "share_url": "The public share URL of the meeting.",
            "meeting_url": "The join URL of the underlying Zoom, Google Meet, Microsoft Teams or Slack huddle call. Null when there is no calendar meeting.",
            "created_at": "When the meeting was created in Fathom.",
            "scheduled_start_time": "The scheduled start time of the calendar event.",
            "scheduled_end_time": "The scheduled end time of the calendar event.",
            "recording_start_time": "When the recording started.",
            "recording_end_time": "When the recording ended.",
            "calendar_invitees_domains_type": "Whether the invitees are all internal (only_internal) or include an external domain (one_or_more_external).",
            "shared_with": "Who the meeting is shared with in the organization: no_teams, single_team, multiple_teams or all_teams.",
            "transcript_language": "The language code of the transcript, for example en.",
            "calendar_invitees": "The calendar invitees, each with name, email, email domain and whether they are external.",
            "recorded_by": "The Fathom user who recorded the meeting, with name, email, email domain and team.",
            "action_items": "The action items from the meeting, each with description, assignee, completion state and recording timestamp.",
            "highlights": "The highlights of the meeting, each with bookmark type, summary and start and end time in seconds.",
            "crm_matches": "The contacts, companies and deals matched in the linked CRM. Holds an error when no CRM is connected.",
        },
    },
    "meeting_summaries": {
        "description": "The summary of a Fathom meeting, made with the account's default summary template.",
        "docs_url": _LIST_MEETINGS_DOCS,
        "columns": {
            "recording_id": "The ID of the meeting recording. Joins to meetings.recording_id.",
            "created_at": "When the meeting was created in Fathom.",
            "default_summary": "The summary, with template_name and the Markdown summary text in markdown_formatted.",
        },
    },
    "meeting_transcripts": {
        "description": "The transcript of a Fathom meeting.",
        "docs_url": _LIST_MEETINGS_DOCS,
        "columns": {
            "recording_id": "The ID of the meeting recording. Joins to meetings.recording_id.",
            "created_at": "When the meeting was created in Fathom.",
            "transcript_language": "The language code of the transcript, for example en.",
            "transcript": "The transcript entries, each with the speaker, the text and an HH:MM:SS timestamp from the start of the meeting.",
        },
    },
    "meeting_types": {
        "description": "A meeting type of the organization. Inactive types can still be on older meetings.",
        "docs_url": "https://developers.fathom.ai/api-reference/meetings/list-meeting-types",
        "columns": {
            "name": "The name of the meeting type. Matches meetings.meeting_type.",
            "status": "Whether the type can be assigned to new meetings (active) or not (inactive).",
            "created_at": "When the meeting type was created.",
        },
    },
    "teams": {
        "description": "A team in the Fathom organization.",
        "docs_url": "https://developers.fathom.ai/api-reference/teams/list-teams",
        "columns": {
            "name": "The name of the team.",
            "created_at": "When the team was created.",
        },
    },
    "team_members": {
        "description": "A member of a team in the Fathom organization.",
        "docs_url": "https://developers.fathom.ai/api-reference/team-members/list-team-members",
        "columns": {
            "name": "The name of the team member.",
            "email": "The email address of the team member.",
            "created_at": "When the team member was added.",
        },
    },
    "users": {
        "description": "A user in the Fathom account, with their permissions. Only an account admin's API key can read users.",
        "docs_url": "https://developers.fathom.ai/api-reference/users/list-users-and-their-permissions",
        "columns": {
            "name": "The name of the user. Null for some invited users.",
            "email": "The email address of the user.",
            "created_at": "When the user was created. For invited users, the date of the invite.",
            "status": "The status of the user: active, deactivated or invited.",
            "permissions": "The settings access and view access levels of the user, with the teams each level applies to. Not set for invited users.",
        },
    },
}
