"""Canonical, documentation-sourced descriptions for xMatters endpoints and columns.

Sourced from the official xMatters REST API reference (https://help.xmatters.com/xmapi/).
Keyed by the endpoint names in `settings.py` `XMATTERS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced xMatters table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most xMatters REST objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier (UUID) for the object.",
    "targetName": "Human-readable name that uniquely identifies the object within the instance.",
    "links": "Object containing a `self` link to retrieve this resource from the API.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "An alert (event) initiated in xMatters, including its status, priority, and timestamps.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-events",
        "columns": _columns(
            eventId="Sequential, human-readable identifier for the event.",
            created="Date and time the event was created; the incremental cursor.",
            terminated="Date and time the event was terminated, if applicable.",
            status="Current status of the event (e.g. ACTIVE, SUSPENDED, TERMINATED).",
            priority="Priority of the event (LOW, MEDIUM, HIGH).",
            eventType="Whether the event is a normal alert or a signal.",
            submitter="The person or system that initiated the event.",
            recipients="The recipients targeted by the event.",
            responseCountsEnabled="Whether response counts are tracked for the event.",
            plan="The communication plan the event belongs to, if any.",
            form="The form used to initiate the event, if any.",
        ),
    },
    "people": {
        "description": "A user in the xMatters instance who can be notified and can respond to events.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-people",
        "columns": _columns(
            firstName="The user's first name.",
            lastName="The user's last name.",
            status="Whether the user is ACTIVE or INACTIVE.",
            externallyOwned="Whether the user is managed by an external system.",
            roles="The roles assigned to the user, which control their permissions.",
            site="The site the user is associated with.",
            timezone="The user's time zone.",
            language="The user's preferred language.",
        ),
    },
    "groups": {
        "description": "A group of recipients used to target and escalate notifications.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-groups",
        "columns": _columns(
            name="The name of the group.",
            status="Whether the group is ACTIVE or INACTIVE.",
            groupType="The type of group (e.g. ON_CALL, BROADCAST, DYNAMIC).",
            description="A description of the group.",
            observedByAll="Whether all users can observe the group.",
            allowDuplicates="Whether duplicate notifications to a recipient are allowed.",
            useDefaultDevices="Whether the group uses recipients' default devices.",
        ),
    },
    "devices": {
        "description": "A contact method (device) belonging to a user, such as email, SMS, or push.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-devices",
        "columns": _columns(
            name="The name of the device (e.g. 'Work Email').",
            deviceType="The type of device (e.g. EMAIL, TEXT_PHONE, VOICE, ANDROID_PUSH).",
            owner="The user who owns the device.",
            status="Whether the device is ACTIVE or INACTIVE.",
            testStatus="Whether the device has been validated.",
            priorityThreshold="The minimum event priority that triggers this device.",
            delay="Delay in minutes before this device is contacted.",
        ),
    },
    "sites": {
        "description": "A physical or logical location that users can be associated with.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-sites",
        "columns": _columns(
            name="The name of the site.",
            status="Whether the site is ACTIVE or INACTIVE.",
            timezone="The time zone of the site.",
            country="The country the site is located in.",
            language="The default language of the site.",
        ),
    },
    "roles": {
        "description": "A role that defines the set of permissions a user has in xMatters.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-roles",
        "columns": _columns(
            name="The name of the role.",
        ),
    },
    "dynamic_teams": {
        "description": "A team whose membership is derived dynamically from user attributes.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-dynamic-teams",
        "columns": _columns(
            name="The name of the dynamic team.",
            recipientType="The recipient type of the team (DYNAMIC_TEAM).",
            observedByAll="Whether all users can observe the team.",
            supervisors="The users who supervise the dynamic team.",
        ),
    },
    "plans": {
        "description": "A communication plan that groups forms, integrations, and configuration used to initiate events.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-plans",
        "columns": _columns(
            name="The name of the communication plan.",
            enabled="Whether the plan is enabled.",
            editable="Whether the plan can be edited.",
            planType="The type of the plan.",
            created="Date and time the plan was created.",
        ),
    },
    "subscriptions": {
        "description": "A subscription that notifies users when events matching its criteria are initiated.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-subscriptions",
        "columns": _columns(
            name="The name of the subscription.",
            description="A description of the subscription.",
            criteria="The criteria events must match to trigger the subscription.",
            owner="The user who owns the subscription.",
            createdDate="Date and time the subscription was created.",
        ),
    },
}
