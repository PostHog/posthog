"""Canonical, documentation-sourced descriptions for Zendesk endpoints and columns.

Sourced from the official Zendesk Support API reference (https://developer.zendesk.com/api-reference/).
Keyed by the resource names in `settings.py` (`BASE_ENDPOINTS` + `SUPPORT_ENDPOINTS`), which match the
`ExternalDataSchema.name` of a synced Zendesk table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Zendesk objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Automatically assigned unique identifier for the object.",
    "url": "API URL of the object.",
    "created_at": "Time the object was created.",
    "updated_at": "Time the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tickets": {
        "description": "A support request submitted by a customer and tracked through to resolution.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/",
        "columns": _columns(
            subject="The value of the subject field for this ticket.",
            raw_subject="The dynamic content placeholder, if present, or the subject value.",
            description="Read-only first comment on the ticket.",
            status="State of the ticket: new, open, pending, hold, solved, or closed.",
            priority="Urgency of the ticket: urgent, high, normal, or low.",
            type="Type of the ticket: problem, incident, question, or task.",
            requester_id="ID of the user who requested this ticket.",
            submitter_id="ID of the user who submitted the ticket.",
            assignee_id="ID of the agent currently assigned to the ticket.",
            organization_id="ID of the organization the ticket's requester belongs to.",
            group_id="ID of the group the ticket is assigned to.",
            brand_id="ID of the brand this ticket is associated with.",
            tags="Array of tags applied to the ticket.",
            satisfaction_rating="The customer satisfaction rating of the ticket, if offered.",
            via="How and where the ticket was created (channel and source).",
            due_at="For tickets of type task, the date the task is due.",
            generated_timestamp="Incremental cursor: timestamp the ticket was last modified.",
            custom_fields="Custom fields for the ticket.",
        ),
    },
    "ticket_fields": {
        "description": "A field that appears on tickets, system or custom, with its type and configuration.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/tickets/ticket_fields/",
        "columns": _columns(
            type="System or custom field type (e.g. subject, text, checkbox, tagger).",
            title="Title of the ticket field shown to agents.",
            title_in_portal="Title shown to end users in the help center.",
            description="Description of the purpose of this ticket field.",
            active="Whether this field is currently available.",
            required="Whether agents must enter a value before solving the ticket.",
            removable="Whether this field can be deleted; false for system fields present on all tickets.",
            position="Relative position of the field on a ticket.",
            custom_field_options="List of selectable options for dropdown-type fields.",
        ),
    },
    "ticket_events": {
        "description": "A record of changes to ticket properties over time, from the incremental ticket events export.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/ticket-management/incremental_exports/#incremental-ticket-event-export",
        "columns": _columns(
            ticket_id="ID of the ticket the event applies to.",
            timestamp="Time the event occurred, as a Unix timestamp.",
            updater_id="ID of the user who made the change.",
            via="How and where the change was made.",
            child_events=(
                "The individual events making up this audit. Comment events carry the full comment "
                "body (public replies and internal notes, distinguished by their `public` flag); "
                "other entries are property changes, notifications, and similar."
            ),
            event_type="Type of the event.",
        ),
    },
    "ticket_metric_events": {
        "description": "Time-series events for ticket metrics such as reply time and resolution time.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/ticket-management/ticket_metric_events/",
        "columns": _columns(
            ticket_id="ID of the ticket the metric event applies to.",
            metric="The metric measured (e.g. agent_work_time, reply_time, resolution_time).",
            instance_id="Identifier grouping events belonging to one metric instance.",
            type="Type of the metric event: activate, fulfill, pause, breach, update_status, or measure.",
            time="Time the metric event occurred.",
            deleted="Whether the metric event has been deleted.",
            status="For update_status events, the calculated status of the metric.",
        ),
    },
    "users": {
        "description": "A person who interacts with Zendesk Support: an end user, agent, or administrator.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/users/users/",
        "columns": _columns(
            name="The user's name.",
            email="The user's primary email address.",
            role="The user's role: end-user, agent, or admin.",
            active="Whether the user is active (false if deleted).",
            verified="Whether any of the user's identities is verified.",
            suspended="Whether the user is suspended (cannot sign in or submit tickets).",
            organization_id="ID of the user's default organization.",
            phone="The user's primary phone number.",
            time_zone="The user's time zone.",
            locale="The user's locale (e.g. en-US).",
            tags="Array of tags applied to the user.",
            last_login_at="Time the user last signed in.",
            external_id="A unique identifier for the user set from another system.",
        ),
    },
    "organizations": {
        "description": "A collection of users grouped into a single account, often a company.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/organizations/organizations/",
        "columns": _columns(
            name="A unique name for the organization.",
            domain_names="An array of domain names associated with this organization.",
            details="Any details about the organization, such as the address.",
            notes="Any notes about the organization.",
            group_id="ID of the group new tickets from this organization are assigned to.",
            shared_tickets="Whether end users in this organization can see each other's tickets.",
            shared_comments="Whether end users in this organization can see each other's comments.",
            tags="Array of tags applied to the organization.",
            external_id="A unique external identifier set from another system.",
        ),
    },
    "groups": {
        "description": "A collection of agents who can be assigned tickets together.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/groups/groups/",
        "columns": _columns(
            name="The name of the group.",
            description="The description of the group.",
            default="Whether this is the default group for the account.",
            is_public="Whether the group is public; if false it is a private group.",
            deleted="Whether the group has been deleted.",
        ),
    },
    "brands": {
        "description": "A customer-facing identity — branding, support address, and help center — within one account.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/account-configuration/brands/",
        "columns": _columns(
            name="The name of the brand.",
            brand_url="The URL of the brand.",
            subdomain="The subdomain of the brand.",
            active="Whether the brand is set as active.",
            default="Whether the brand is the default brand for this account.",
            has_help_center="Whether the brand has a help center.",
            host_mapping="The hostmapping to this brand, if any (only admins can update).",
        ),
    },
    "sla_policies": {
        "description": "A service level agreement policy defining target response and resolution times for tickets.",
        "docs_url": "https://developer.zendesk.com/api-reference/ticketing/business-rules/sla_policies/",
        "columns": _columns(
            title="The title of the SLA policy.",
            description="The description of the SLA policy.",
            position="Position of the policy, determining the order it is matched in.",
            filter="The conditions used to match tickets to this policy.",
            policy_metrics="The metric targets (e.g. first reply time) for each priority level.",
        ),
    },
}
