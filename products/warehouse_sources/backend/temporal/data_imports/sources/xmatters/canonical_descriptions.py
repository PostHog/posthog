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
    "incidents": {
        "description": "An incident tracked by xMatters incident management, with its severity, status, and impacted services.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-incidents",
        "columns": _columns(
            incidentIdentifier="The alpha-numeric incident number, for example INC-145.",
            summary="The title of the incident.",
            description="The description of the incident.",
            severity="The severity of the incident (CRITICAL, HIGH, MEDIUM, LOW, MINIMAL).",
            status="The status of the incident (OPEN, IN_PROGRESS, MITIGATED, RESOLVED, REJECTED).",
            initiatedBy="The person, or the credentials, that created the incident.",
            commander="The person responsible for the incident.",
            requestId="The identifier returned from the request that triggered the incident.",
            impactedServices="The services that the incident impacts.",
            createdAt="Date and time the incident was created.",
            updatedAt="Date and time the incident was last updated.",
        ),
    },
    "audits": {
        "description": "An audit record for an event: a status change, a comment, or a recipient's response to a notification.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-event-audit-information",
        "columns": {
            "id": "Unique identifier (UUID) for the audit record.",
            "event_id": "Identifier of the event that the audit record belongs to.",
            "type": "The audit type, for example EVENT_CREATED, EVENT_ANNOTATED, or RESPONSE_RECEIVED.",
            "at": "Date and time (UTC) the audit record was added to the event.",
            "annotation": "For EVENT_ANNOTATED records, the comment and the person who made it.",
            "response": "For RESPONSE_RECEIVED records, the response a recipient gave to a notification.",
            "orderId": "Deprecated sequential identifier for the audit record.",
        },
    },
    "group_members": {
        "description": "A membership of a person, device, or group in an xMatters group.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-group-members",
        "columns": {
            "group_id": "Identifier of the group.",
            "member_id": "Identifier of the member (person, device, or group).",
            "group": "Reference to the group.",
            "member": "Reference to the member, including its recipient type.",
        },
    },
    "group_shifts": {
        "description": "An on-call shift in a group, with its schedule, recurrence, and rotation.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-shifts",
        "columns": _columns(
            group_id="Identifier of the group that owns the shift.",
            group="Reference to the group that owns the shift.",
            name="The name of the shift.",
            description="A description of the shift.",
            start="The start time of the shift.",
            end="The end time of the shift.",
            created="Date and time the shift was created.",
            timezone="The time zone the shift occurs in.",
            recurrence="How the shift repeats.",
            rotation="How members rotate through the shift.",
        ),
    },
    "services": {
        "description": "A service in the xMatters service catalog, with its type, tier, and owning group.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-services",
        "columns": _columns(
            recipientType="Always SERVICE.",
            description="A description of the service.",
            serviceType="APPLICATION for an interface between business services, TECHNICAL for any other service.",
            serviceTier="The importance level of the service: PLATINUM, GOLD, SILVER, BRONZE, or NONE.",
            ownedBy="Reference to the group that owns the service.",
        ),
    },
    "signals": {
        "description": "An inbound signal (alert or request) that xMatters received from a trigger.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-signals",
        "columns": {
            "id": "Unique identifier (UUID) for the signal.",
            "received": "Date and time xMatters received the signal; the incremental cursor.",
            "httpResponse": "The HTTP response xMatters returned for the signal.",
            "workflow": "Reference to the workflow (plan) the signal was sent to.",
            "workflowType": "The type of the workflow, for example USER or RESERVED.",
            "trigger": "Reference to the trigger that received the signal.",
            "triggerLabel": "User-provided name of the trigger that sent the signal.",
            "triggerType": "The type of the trigger, for example INBOUND_WEBHOOK.",
            "authenticatedUser": "The user that authenticated the inbound request.",
            "suppressedCount": "Number of correlated signals suppressed by flood control settings.",
            "payloadType": "The content type of the signal payload.",
        },
    },
    "user_deliveries": {
        "description": "Delivery and response outcome of an event for one notified user, from historical data.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-user-delivery-data",
        "columns": {
            "event_id": "Identifier of the event that the user was notified about.",
            "person_id": "Identifier of the notified user.",
            "event": "Reference to the event.",
            "person": "Reference to the notified user.",
            "deliveryStatus": "Consolidated status across all notifications sent to the user's devices, for example RESPONDED or FAILED.",
            "notifications": "The notifications sent to the user's devices, with delivery times and responses.",
            "response": "The response the user gave to the event, if any.",
        },
    },
    "on_call": {
        "description": "A shift occurrence that is on call now for an on-call group, with the members on duty.",
        "docs_url": "https://help.xmatters.com/xmapi/index.html#get-who-is-on-call",
        "columns": {
            "group_id": "Identifier of the group.",
            "shift_id": "Identifier of the shift.",
            "group": "Reference to the group.",
            "shift": "Reference to the shift.",
            "start": "Start of the shift occurrence (UTC).",
            "end": "End of the shift occurrence (UTC).",
            "members": "The members of the shift occurrence, in escalation order.",
            "occurrenceType": "The type of shift occurrence, for example SHIFT_OCCURRENCE.",
        },
    },
}
