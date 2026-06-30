"""Canonical, documentation-sourced descriptions for ServiceNow streams and columns.

Sourced from the official ServiceNow product documentation for the ITSM tables exposed via the
Table API (https://docs.servicenow.com/). Keyed by the friendly stream names in `settings.py`
`SERVICENOW_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced ServiceNow table.
Each maps to a canonical ServiceNow table (e.g. `incidents` -> `incident`). Columns absent here
fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Audit and base-task fields present on every ServiceNow record; merged into each entry.
_COMMON_COLUMNS = {
    "sys_id": "Unique 32-character identifier for the record.",
    "sys_created_on": "Date and time the record was created.",
    "sys_created_by": "User who created the record.",
    "sys_updated_on": "Date and time the record was last updated.",
    "sys_updated_by": "User who last updated the record.",
    "sys_mod_count": "Number of times the record has been updated.",
}

# Fields common to all task-derived tables (incident, problem, change_request, sc_task, etc.).
_TASK_COLUMNS = {
    "number": "Human-readable reference number for the record (e.g. INC0010001).",
    "short_description": "Brief summary of the record.",
    "description": "Detailed description of the record.",
    "state": "Current state of the record (e.g. New, In Progress, Closed).",
    "priority": "Priority of the record.",
    "urgency": "Urgency of the record.",
    "impact": "Impact of the record.",
    "assigned_to": "User the record is assigned to.",
    "assignment_group": "Group the record is assigned to.",
    "opened_by": "User who opened the record.",
    "opened_at": "Date and time the record was opened.",
    "closed_by": "User who closed the record.",
    "closed_at": "Date and time the record was closed.",
}


def _task_columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **_TASK_COLUMNS, **overrides}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "An unplanned interruption or reduction in quality of an IT service (ServiceNow `incident` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-it-service-management/page/product/incident-management/concept/c_IncidentManagement.html",
        "columns": _task_columns(
            caller_id="User who reported the incident.",
            category="Category of the incident.",
            subcategory="Subcategory of the incident.",
            severity="Severity of the incident.",
            resolved_at="Date and time the incident was resolved.",
            resolved_by="User who resolved the incident.",
            close_code="Resolution code applied when closing the incident.",
            close_notes="Notes recorded when the incident was closed.",
            cmdb_ci="Configuration item affected by the incident.",
        ),
    },
    "problems": {
        "description": "The underlying cause of one or more incidents (ServiceNow `problem` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-it-service-management/page/product/problem-management/concept/c_ProblemManagement.html",
        "columns": _task_columns(
            category="Category of the problem.",
            known_error="Whether the problem is a known error.",
            workaround="Documented workaround for the problem.",
            cause_notes="Notes describing the root cause of the problem.",
            cmdb_ci="Configuration item affected by the problem.",
        ),
    },
    "change_requests": {
        "description": "A request to add, modify, or remove anything that could affect IT services (ServiceNow `change_request` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-it-service-management/page/product/change-management/concept/c_ITILChangeManagement.html",
        "columns": _task_columns(
            type="Type of change (e.g. standard, normal, emergency).",
            risk="Assessed risk of the change.",
            category="Category of the change.",
            start_date="Planned start date of the change.",
            end_date="Planned end date of the change.",
            requested_by="User who requested the change.",
            cmdb_ci="Configuration item affected by the change.",
            approval="Approval status of the change.",
        ),
    },
    "change_tasks": {
        "description": "A task carried out as part of a change request (ServiceNow `change_task` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-it-service-management/page/product/change-management/concept/c_ChangeTasks.html",
        "columns": _task_columns(
            change_request="The change request this task belongs to.",
            change_task_type="Type of change task.",
            planned_start_date="Planned start date of the task.",
            planned_end_date="Planned end date of the task.",
        ),
    },
    "tasks": {
        "description": "The base task record that all task-based tables extend (ServiceNow `task` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-platform-administration/page/administer/task-tables/concept/c_TaskTables.html",
        "columns": _task_columns(),
    },
    "catalog_requests": {
        "description": "A request for one or more catalog items, submitted through the service catalog (ServiceNow `sc_request` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-servicenow-platform/page/product/service-catalog-management/concept/c_RequestManagement.html",
        "columns": _task_columns(
            requested_for="User the request was submitted for.",
            request_state="State of the overall request.",
            approval="Approval status of the request.",
            price="Total price of the request.",
        ),
    },
    "requested_items": {
        "description": "An individual catalog item within a catalog request (ServiceNow `sc_req_item` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-servicenow-platform/page/product/service-catalog-management/concept/c_RequestedItems.html",
        "columns": _task_columns(
            request="The parent catalog request this item belongs to.",
            cat_item="The catalog item that was requested.",
            quantity="Quantity of the item requested.",
            price="Unit price of the requested item.",
            stage="Fulfillment stage of the requested item.",
        ),
    },
    "catalog_tasks": {
        "description": "A fulfillment task for a requested catalog item (ServiceNow `sc_task` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-servicenow-platform/page/product/service-catalog-management/concept/c_CatalogTask.html",
        "columns": _task_columns(
            request="The catalog request this task belongs to.",
            request_item="The requested item this task fulfills.",
        ),
    },
    "users": {
        "description": "A user account in the ServiceNow instance (ServiceNow `sys_user` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-platform-administration/page/administer/users-and-groups/concept/c_UserAdministration.html",
        "columns": _columns(
            user_name="The user's login name.",
            name="The user's full name.",
            first_name="The user's first name.",
            last_name="The user's last name.",
            email="The user's email address.",
            active="Whether the user account is active.",
            title="The user's job title.",
            department="The user's department.",
            manager="The user's manager.",
            phone="The user's phone number.",
            location="The user's location.",
        ),
    },
    "user_groups": {
        "description": "A group of users, used for assignment and notifications (ServiceNow `sys_user_group` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-platform-administration/page/administer/users-and-groups/concept/c_Groups.html",
        "columns": _columns(
            name="Name of the group.",
            description="Description of the group.",
            active="Whether the group is active.",
            manager="User who manages the group.",
            parent="Parent group, if part of a hierarchy.",
            type="Type of the group.",
            email="Email address associated with the group.",
        ),
    },
    "configuration_items": {
        "description": "A configuration item (CI) in the CMDB representing a managed asset or service (ServiceNow `cmdb_ci` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-servicenow-platform/page/product/configuration-management/concept/c_ConfigurationManagementCMDB.html",
        "columns": _columns(
            name="Name of the configuration item.",
            asset_tag="Asset tag of the configuration item.",
            serial_number="Serial number of the configuration item.",
            model_id="Model of the configuration item.",
            manufacturer="Manufacturer of the configuration item.",
            install_status="Installation status of the configuration item.",
            assigned_to="User the configuration item is assigned to.",
            location="Location of the configuration item.",
            category="Category of the configuration item.",
            operational_status="Operational status of the configuration item.",
        ),
    },
    "knowledge_articles": {
        "description": "A knowledge base article (ServiceNow `kb_knowledge` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-servicenow-platform/page/product/knowledge-management/concept/c_KnowledgeManagement.html",
        "columns": _columns(
            number="Reference number of the article.",
            short_description="Title or short description of the article.",
            text="Body text of the article.",
            kb_knowledge_base="The knowledge base the article belongs to.",
            kb_category="Category of the article.",
            workflow_state="Workflow state of the article (e.g. draft, published).",
            author="Author of the article.",
            published="Date the article was published.",
            valid_to="Date the article expires.",
        ),
    },
    "assets": {
        "description": "An asset tracked in asset management (ServiceNow `alm_asset` table).",
        "docs_url": "https://docs.servicenow.com/bundle/utah-it-asset-management/page/product/asset-management/concept/c_AssetManagement.html",
        "columns": _columns(
            asset_tag="Asset tag of the asset.",
            display_name="Display name of the asset.",
            serial_number="Serial number of the asset.",
            model="Model of the asset.",
            model_category="Model category of the asset.",
            install_status="Installation status of the asset.",
            assigned_to="User the asset is assigned to.",
            cost="Cost of the asset.",
            quantity="Quantity of the asset.",
            location="Location of the asset.",
        ),
    },
}
