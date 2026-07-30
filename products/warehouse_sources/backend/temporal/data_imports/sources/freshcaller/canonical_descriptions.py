"""Canonical, documentation-sourced descriptions for Freshcaller endpoints and columns.

Sourced from the official Freshcaller API reference (https://developers.freshcaller.com/api/).
Keyed by the endpoint names in `settings.py` `FRESHCALLER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Freshcaller table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "An agent or admin in your Freshcaller account who can handle calls.",
        "docs_url": "https://developers.freshcaller.com/api/#users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's name.",
            "email": "The user's email address.",
            "phone": "The user's phone number.",
            "status": "Availability status (0 offline, 1 online, 2 busy, 3 after call work).",
            "last_call_time": "Time the user last handled a call.",
            "last_seen_time": "Time the user was last active.",
            "confirmed": "Whether the account has been activated via email.",
            "language": "The user's preferred conversational language.",
            "time_zone": "The user's selected time zone.",
            "deleted": "Whether the user's information has been deleted.",
            "role": "The user's role (Account Admin, Admin, Supervisor, or Agent).",
            "teams": "The teams the user belongs to.",
        },
    },
    "teams": {
        "description": "A group of agents in Freshcaller used to route and organize calls.",
        "docs_url": "https://developers.freshcaller.com/api/#teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "The team's name.",
            "description": "The team's description.",
            "users": "The users belonging to the team.",
            "omni_channel": "Whether omni-channel routing is enabled for the team.",
        },
    },
    "calls": {
        "description": "A phone call handled through Freshcaller, inbound or outbound.",
        "docs_url": "https://developers.freshcaller.com/api/#calls",
        "columns": {
            "id": "Unique identifier for the call.",
            "direction": "Whether the call was Incoming or Outgoing.",
            "parent_call_id": "Parent call identifier for transferred calls.",
            "root_call_id": "Source call identifier for child calls.",
            "phone_number_id": "Identifier of the Freshcaller number used.",
            "phone_number": "The Freshcaller number used for the call.",
            "assigned_agent_id": "Identifier of the primary agent on the call.",
            "assigned_agent_name": "Name of the primary agent on the call.",
            "assigned_team_id": "Team identifier for inbound calls.",
            "assigned_team_name": "Team name for inbound calls.",
            "assigned_call_queue_id": "Call queue identifier for inbound calls.",
            "assigned_call_queue_name": "Call queue name for inbound calls.",
            "assigned_ivr_id": "IVR menu identifier for inbound calls.",
            "assigned_ivr_name": "IVR menu name for inbound calls.",
            "call_notes": "Notes entered by an agent during or after the call.",
            "bill_duration": "Duration used to calculate the call cost.",
            "bill_duration_unit": "Time unit for bill_duration.",
            "created_time": "Time at which the call was initiated.",
            "updated_time": "Time at which the call's attributes were last updated.",
            "recording": "Recording details for the call (id, url, transcription, duration).",
            "integrated_resources": "Integration and resource details related to the call.",
            "participants": "The participants on the call.",
        },
    },
    "call_metrics": {
        "description": "Per-call performance metrics for a Freshcaller call (hold time, talk time, cost, etc.).",
        "docs_url": "https://developers.freshcaller.com/api/#call-metrics",
        "columns": {
            "id": "Unique identifier for the call metric.",
            "call_id": "Identifier of the associated call.",
            "created_time": "Time at which the metric object was created.",
            "updated_time": "Time at which the metric object was last updated.",
            "ivr_time": "Total time the customer spent in the IVR.",
            "hold_duration": "Total time the customer spent on hold.",
            "call_work_time": "Time the agent spent on post-call activities.",
            "total_ringing_time": "Ringing/wait time before the call was answered.",
            "talk_time": "Total talk time, excluding after-call work and hold.",
            "answering_speed": "Inbound wait time before the call was answered.",
            "recording_duration": "Duration for which the call was recorded.",
            "bill_duration": "Duration used to calculate the call cost.",
            "cost": "Cost associated with the call.",
            "cost_unit": "Currency (ISO code) for the cost.",
            "csat": "CSAT feedback details for the call.",
            "tags": "Labels associated with the call.",
            "life_cycle": "The sequence of call events (included via the life_cycle parameter).",
        },
    },
}
