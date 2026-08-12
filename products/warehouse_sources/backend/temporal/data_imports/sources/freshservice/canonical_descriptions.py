"""Canonical, documentation-sourced descriptions for Freshservice endpoints and columns.

Sourced from the official Freshservice API v2 reference (https://api.freshservice.com/).
Keyed by the endpoint names in `settings.py` `FRESHSERVICE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Freshservice table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Freshservice objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tickets": {
        "description": "A service request or incident raised by a requester and tracked through to resolution.",
        "docs_url": "https://api.freshservice.com/#tickets",
        "columns": _columns(
            subject="Subject of the ticket.",
            description="Description (body) of the ticket, in HTML.",
            description_text="Plain-text version of the ticket description.",
            status="Status of the ticket (2=open, 3=pending, 4=resolved, 5=closed).",
            priority="Priority of the ticket (1=low, 2=medium, 3=high, 4=urgent).",
            source="Channel the ticket came in through (1=email, 2=portal, 3=phone, …).",
            type="Type categorizing the ticket (e.g. Incident, Service Request).",
            requester_id="ID of the requester who raised the ticket.",
            responder_id="ID of the agent the ticket is assigned to.",
            group_id="ID of the agent group the ticket is assigned to.",
            department_id="ID of the department the requester belongs to.",
            email="Email address of the requester.",
            category="Ticket category.",
            sub_category="Ticket sub-category.",
            item_category="Ticket item category.",
            tags="List of tags applied to the ticket.",
            due_by="Time by which the ticket is due for resolution.",
            fr_due_by="Time by which the first response is due.",
            spam="Whether the ticket has been marked as spam.",
        ),
    },
    "problems": {
        "description": "A problem record tracking the root cause behind one or more incidents.",
        "docs_url": "https://api.freshservice.com/#problems",
        "columns": _columns(
            subject="Subject of the problem.",
            description="Description of the problem, in HTML.",
            status="Status of the problem (1=open, 2=change requested, 3=closed).",
            priority="Priority of the problem (1=low, 2=medium, 3=high, 4=urgent).",
            impact="Impact of the problem (1=low, 2=medium, 3=high).",
            agent_id="ID of the agent the problem is assigned to.",
            group_id="ID of the agent group the problem is assigned to.",
            department_id="ID of the department the problem relates to.",
            due_by="Time by which the problem is due to be resolved.",
        ),
    },
    "changes": {
        "description": "A change request tracking a planned modification to the IT environment.",
        "docs_url": "https://api.freshservice.com/#changes",
        "columns": _columns(
            subject="Subject of the change.",
            description="Description of the change, in HTML.",
            status="Status of the change (1=open, 2=planning, 3=approval, 4=pending release, 5=pending review, 6=closed).",
            priority="Priority of the change (1=low, 2=medium, 3=high, 4=urgent).",
            impact="Impact of the change (1=low, 2=medium, 3=high).",
            risk="Risk of the change (1=minor, 2=standard, 3=major, 4=high).",
            change_type="Type of change (1=minor, 2=standard, 3=major, 4=emergency).",
            agent_id="ID of the agent the change is assigned to.",
            group_id="ID of the agent group the change is assigned to.",
            department_id="ID of the department the change relates to.",
            planned_start_date="Planned start of the change.",
            planned_end_date="Planned end of the change.",
        ),
    },
    "releases": {
        "description": "A release record tracking the rollout of changes to production.",
        "docs_url": "https://api.freshservice.com/#releases",
        "columns": _columns(
            subject="Subject of the release.",
            description="Description of the release, in HTML.",
            status="Status of the release (1=open, 2=on hold, 3=in progress, 4=incomplete, 5=completed).",
            priority="Priority of the release (1=low, 2=medium, 3=high, 4=urgent).",
            release_type="Type of release (1=minor, 2=standard, 3=major, 4=emergency).",
            agent_id="ID of the agent the release is assigned to.",
            group_id="ID of the agent group the release is assigned to.",
            department_id="ID of the department the release relates to.",
            planned_start_date="Planned start of the release.",
            planned_end_date="Planned end of the release.",
        ),
    },
    "requesters": {
        "description": "An end user who can raise tickets with the service desk.",
        "docs_url": "https://api.freshservice.com/#requesters",
        "columns": _columns(
            first_name="The requester's first name.",
            last_name="The requester's last name.",
            primary_email="The requester's primary email address.",
            secondary_emails="The requester's additional email addresses.",
            work_phone_number="The requester's work phone number.",
            mobile_phone_number="The requester's mobile phone number.",
            department_ids="IDs of the departments the requester belongs to.",
            job_title="The requester's job title.",
            location_id="ID of the requester's location.",
            active="Whether the requester is active.",
            time_zone="The requester's time zone.",
            language="The requester's language.",
        ),
    },
    "requester_groups": {
        "description": "A group of requesters, used to scope access and automation.",
        "docs_url": "https://api.freshservice.com/#requester-groups",
        "columns": _columns(
            name="The requester group's name.",
            description="Description of the requester group.",
            type="Type of the requester group (manual or rule_based).",
        ),
    },
    "agents": {
        "description": "A service desk agent who responds to and works on tickets.",
        "docs_url": "https://api.freshservice.com/#agents",
        "columns": _columns(
            first_name="The agent's first name.",
            last_name="The agent's last name.",
            email="The agent's email address.",
            occasional="Whether the agent is an occasional (vs. full-time) agent.",
            active="Whether the agent is active.",
            department_ids="IDs of the departments the agent belongs to.",
            group_ids="IDs of the agent groups the agent belongs to.",
            role_ids="IDs of the roles assigned to the agent.",
            location_id="ID of the agent's location.",
            time_zone="The agent's time zone.",
        ),
    },
    "agent_groups": {
        "description": "A group of agents that tickets can be assigned to.",
        "docs_url": "https://api.freshservice.com/#groups",
        "columns": _columns(
            name="The group's name.",
            description="Description of the group.",
            agent_ids="IDs of the agents in the group.",
            business_hours_id="ID of the business hours applied to the group.",
            escalate_to="ID of the agent tickets escalate to.",
        ),
    },
    "agent_roles": {
        "description": "A role defining the set of privileges granted to agents.",
        "docs_url": "https://api.freshservice.com/#roles",
        "columns": _columns(
            name="The role's name.",
            description="Description of the role.",
            default="Whether this is a default (system) role.",
        ),
    },
    "assets": {
        "description": "A configuration item (hardware, software, or other tracked asset) in the CMDB.",
        "docs_url": "https://api.freshservice.com/#assets",
        "columns": _columns(
            display_id="Human-readable identifier for the asset.",
            name="The asset's name.",
            description="Description of the asset.",
            asset_type_id="ID of the asset type.",
            impact="Impact level of the asset (1=low, 2=medium, 3=high).",
            usage_type="Usage type of the asset (loaner or permanent).",
            user_id="ID of the user the asset is assigned to.",
            department_id="ID of the department the asset belongs to.",
            location_id="ID of the asset's location.",
            agent_id="ID of the agent managing the asset.",
            group_id="ID of the agent group managing the asset.",
        ),
    },
    "asset_types": {
        "description": "A classification for assets in the CMDB (e.g. Hardware, Software, Business Service).",
        "docs_url": "https://api.freshservice.com/#asset-types",
        "columns": _columns(
            name="The asset type's name.",
            description="Description of the asset type.",
            parent_asset_type_id="ID of the parent asset type, if any.",
            visible="Whether the asset type is visible.",
        ),
    },
    "software": {
        "description": "A software application tracked for software asset management.",
        "docs_url": "https://api.freshservice.com/#software",
        "columns": _columns(
            name="The application's name.",
            description="Description of the application.",
            application_type="Type of application (desktop, saas, or mobile).",
            status="Status of the application (blacklisted, ignored, or managed).",
            publisher_id="ID of the application's publisher.",
            managed_by_id="ID of the agent managing the application.",
            category="Category of the application.",
        ),
    },
    "purchase_orders": {
        "description": "A purchase order for procuring assets or services.",
        "docs_url": "https://api.freshservice.com/#purchase-order",
        "columns": _columns(
            name="Name of the purchase order.",
            po_number="Purchase order number.",
            vendor_id="ID of the vendor the order is placed with.",
            status="Status of the purchase order (20=open, 25=ordered, 30=partially received, 35=received, 40=cancelled).",
            department_id="ID of the department the order is for.",
            expected_delivery_date="Expected delivery date.",
            total_cost="Total cost of the purchase order.",
        ),
    },
    "products": {
        "description": "A product in the product catalog that assets can be associated with.",
        "docs_url": "https://api.freshservice.com/#products",
        "columns": _columns(
            name="The product's name.",
            description="Description of the product.",
            asset_type_id="ID of the asset type the product maps to.",
            manufacturer="Manufacturer of the product.",
            status="Status of the product (In Production, In Pipeline, or Retired).",
        ),
    },
    "vendors": {
        "description": "A vendor or supplier that assets and purchase orders are associated with.",
        "docs_url": "https://api.freshservice.com/#vendors",
        "columns": _columns(
            name="The vendor's name.",
            description="Description of the vendor.",
            primary_contact_id="ID of the vendor's primary contact.",
            address="The vendor's address.",
        ),
    },
    "locations": {
        "description": "A physical location (site or office) that assets and users are associated with.",
        "docs_url": "https://api.freshservice.com/#locations",
        "columns": _columns(
            name="The location's name.",
            parent_location_id="ID of the parent location, if any.",
            primary_contact_id="ID of the location's primary contact.",
            address="The location's address.",
        ),
    },
    "departments": {
        "description": "A department that groups together requesters within the organization.",
        "docs_url": "https://api.freshservice.com/#departments",
        "columns": _columns(
            name="The department's name.",
            description="Description of the department.",
            head_user_id="ID of the user who heads the department.",
            prime_user_id="ID of the department's prime user.",
            domains="Email domains associated with the department.",
        ),
    },
}
