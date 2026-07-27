"""Canonical, documentation-sourced descriptions for Freshdesk endpoints and columns.

Sourced from the official Freshdesk API v2 reference (https://developers.freshdesk.com/api/).
Keyed by the endpoint names in `settings.py` `FRESHDESK_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Freshdesk table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Freshdesk objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tickets": {
        "description": "A support request raised by a customer and tracked through to resolution.",
        "docs_url": "https://developers.freshdesk.com/api/#tickets",
        "columns": _columns(
            subject="Subject of the ticket.",
            description="Description (body) of the ticket, in HTML.",
            description_text="Plain-text version of the ticket description.",
            status="Status of the ticket (2=open, 3=pending, 4=resolved, 5=closed).",
            priority="Priority of the ticket (1=low, 2=medium, 3=high, 4=urgent).",
            source="Channel the ticket came in through (1=email, 2=portal, 3=phone, …).",
            type="Type categorizing the ticket (e.g. Question, Incident, Problem).",
            requester_id="ID of the contact who requested support.",
            responder_id="ID of the agent the ticket is assigned to.",
            group_id="ID of the group the ticket is assigned to.",
            company_id="ID of the company the requester belongs to.",
            email="Email address of the requester.",
            tags="List of tags applied to the ticket.",
            due_by="Time by which the ticket is due for resolution.",
            fr_due_by="Time by which the first response is due.",
            spam="Whether the ticket has been marked as spam.",
        ),
    },
    "contacts": {
        "description": "A customer or requester who can raise tickets with the helpdesk.",
        "docs_url": "https://developers.freshdesk.com/api/#contacts",
        "columns": _columns(
            name="The contact's full name.",
            email="The contact's primary email address.",
            phone="The contact's phone number.",
            mobile="The contact's mobile number.",
            company_id="ID of the company the contact belongs to.",
            active="Whether the contact has been verified.",
            address="The contact's address.",
            job_title="The contact's job title.",
            time_zone="The contact's time zone.",
            language="The contact's language.",
            tags="List of tags applied to the contact.",
        ),
    },
    "companies": {
        "description": "An organization that groups together related contacts.",
        "docs_url": "https://developers.freshdesk.com/api/#companies",
        "columns": _columns(
            name="The company's name.",
            description="Description of the company.",
            domains="List of email domains associated with the company.",
            note="Free-form note about the company.",
            health_score="The company's health score.",
            account_tier="Account tier of the company.",
            industry="Industry the company operates in.",
        ),
    },
    "agents": {
        "description": "A helpdesk agent who responds to and works on tickets.",
        "docs_url": "https://developers.freshdesk.com/api/#agents",
        "columns": _columns(
            available="Whether the agent is accepting new tickets.",
            occasional="Whether the agent is an occasional (vs. full-time) agent.",
            ticket_scope="Scope of tickets the agent can access (1=global, 2=group, 3=restricted).",
            group_ids="IDs of the groups the agent belongs to.",
            role_ids="IDs of the roles assigned to the agent.",
            contact="The agent's contact details (name, email, phone).",
        ),
    },
    "groups": {
        "description": "A group of agents that tickets can be assigned to.",
        "docs_url": "https://developers.freshdesk.com/api/#groups",
        "columns": _columns(
            name="The group's name.",
            description="Description of the group.",
            agent_ids="IDs of the agents in the group.",
            business_hour_id="ID of the business hours applied to the group.",
        ),
    },
    "roles": {
        "description": "A role defining the set of privileges granted to agents.",
        "docs_url": "https://developers.freshdesk.com/api/#roles",
        "columns": _columns(
            name="The role's name.",
            description="Description of the role.",
            default="Whether this is a default (system) role.",
        ),
    },
    "products": {
        "description": "A product that tickets can be associated with.",
        "docs_url": "https://developers.freshdesk.com/api/#products",
        "columns": _columns(
            name="The product's name.",
            description="Description of the product.",
        ),
    },
    "skills": {
        "description": "A skill used to route tickets to agents with matching expertise.",
        "docs_url": "https://developers.freshdesk.com/api/#skills",
        "columns": _columns(
            name="The skill's name.",
            rank="Rank determining the skill's priority during routing.",
            agent_ids="IDs of the agents who have this skill.",
        ),
    },
    "ticket_fields": {
        "description": "A field on the ticket form, default or custom.",
        "docs_url": "https://developers.freshdesk.com/api/#ticket-fields",
        "columns": _columns(
            label="Label shown to agents for the field.",
            label_for_customers="Label shown to customers for the field.",
            name="Internal name of the field.",
            type="Data type of the field.",
            default="Whether this is a default (system) field.",
            required_for_closure="Whether the field is required to close a ticket.",
            position="Display position of the field on the form.",
        ),
    },
    "time_entries": {
        "description": "A record of time logged by an agent against a ticket.",
        "docs_url": "https://developers.freshdesk.com/api/#time-entries",
        "columns": _columns(
            ticket_id="ID of the ticket the time was logged against.",
            agent_id="ID of the agent who logged the time.",
            time_spent="Duration of time spent, in HH:MM.",
            billable="Whether the time entry is billable.",
            note="Note describing the work done.",
            timer_running="Whether the timer is currently running.",
            start_time="Time at which the timer was started.",
            executed_at="Time at which the work was performed.",
        ),
    },
    "satisfaction_ratings": {
        "description": "A customer satisfaction (CSAT) rating submitted for a ticket.",
        "docs_url": "https://developers.freshdesk.com/api/#csat",
        "columns": _columns(
            survey_id="ID of the satisfaction survey.",
            ticket_id="ID of the ticket the rating is for.",
            agent_id="ID of the agent who handled the ticket.",
            group_id="ID of the group the ticket was assigned to.",
            ratings="Map of survey question IDs to the customer's ratings.",
            feedback="Free-form feedback left by the customer.",
            user_id="ID of the customer who submitted the rating.",
        ),
    },
    "sla_policies": {
        "description": "An SLA policy defining response and resolution time targets for tickets.",
        "docs_url": "https://developers.freshdesk.com/api/#sla-policies",
        "columns": _columns(
            name="The SLA policy's name.",
            description="Description of the SLA policy.",
            position="Order in which the policy is evaluated.",
            active="Whether the SLA policy is active.",
            is_default="Whether this is the default SLA policy.",
            sla_target="Response and resolution targets per priority.",
        ),
    },
    "business_hours": {
        "description": "A set of working hours and holidays used for SLA calculations.",
        "docs_url": "https://developers.freshdesk.com/api/#business-hours",
        "columns": _columns(
            name="The business hours configuration's name.",
            description="Description of the business hours.",
            time_zone="Time zone the business hours apply in.",
            is_default="Whether this is the default business hours.",
            business_hours="Working hours for each day of the week.",
        ),
    },
    "canned_response_folders": {
        "description": "A folder grouping related canned (pre-written) agent responses.",
        "docs_url": "https://developers.freshdesk.com/api/#canned-response-folders",
        "columns": _columns(
            name="The folder's name.",
            personal="Whether the folder is personal to a single agent.",
            responses_count="Number of canned responses in the folder.",
        ),
    },
}
