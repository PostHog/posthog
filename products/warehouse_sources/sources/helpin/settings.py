from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

HELPIN_CLOUD_API_HOST = "https://api.helpin.ai"
API_PATH_PREFIX = "/public/v1"

# Helpin fails a whole call with a 500 when its JSON result is larger than 256 KiB, so the endpoints
# with large rows (support conversations and messages carry message bodies) read small pages.
CONVERSATIONS_PAGE_SIZE = 25
MESSAGES_PAGE_SIZE = 20

# "paged": the body has `data.next_offset`, which is null on the last page.
# "single": the endpoint takes only `limit` (max 100) and has no paging at all.
Pagination = Literal["paged", "single"]

# How a server-side updated-time filter is sent:
# "updated_after": the `updated_after=YYYY-MM-DD` query param of /tasks.
# "crm_filter": a JSON `filter` rule `updated_at on_or_after YYYY-MM-DD` on the CRM lists.
UpdatedFilter = Literal["updated_after", "crm_filter"]


@frozen
class HelpinEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: list[str]
    scope: str
    page_size: int = 100
    pagination: Pagination = "paged"
    params: dict[str, Any] = field(default_factory=dict)
    # Each pass reads the list again with these extra params, for lists that hide some rows by default.
    passes: tuple[dict[str, Any], ...] = ()
    # A stable creation-time field. Never a last-updated field: those move rows between partitions.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    updated_filter: Optional[UpdatedFilter] = None
    fanout: Optional[DependentEndpointConfig] = None


_UPDATED_AT: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    }
]

HELPIN_ENDPOINTS: dict[str, HelpinEndpointConfig] = {
    "support_conversations": HelpinEndpointConfig(
        name="support_conversations",
        path="/support/conversations",
        data_selector="data.items",
        primary_keys=["id"],
        scope="helpin.support.read",
        page_size=CONVERSATIONS_PAGE_SIZE,
        partition_key="created_at",
    ),
    "support_conversation_messages": HelpinEndpointConfig(
        name="support_conversation_messages",
        path="/support/conversations/{conversation_id}/messages",
        data_selector="data.items",
        primary_keys=["id"],
        scope="helpin.support.read",
        page_size=MESSAGES_PAGE_SIZE,
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="support_conversations",
            resolve_param="conversation_id",
            resolve_field="id",
            # Each message row already carries its `conversation_id`.
            include_from_parent=[],
            # A conversation merged or deleted between the list call and its messages call.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "support_inboxes": HelpinEndpointConfig(
        name="support_inboxes",
        path="/support/inboxes",
        data_selector="data.inboxes",
        primary_keys=["id"],
        scope="helpin.support.read",
        pagination="single",
    ),
    "support_tags": HelpinEndpointConfig(
        name="support_tags",
        path="/support/tags",
        data_selector="data.tags",
        primary_keys=["id"],
        scope="helpin.support.read",
        pagination="single",
    ),
    "crm_contacts": HelpinEndpointConfig(
        name="crm_contacts",
        path="/crm/contacts",
        data_selector="data.contacts",
        primary_keys=["id"],
        scope="helpin.crm.read",
        page_size=50,
    ),
    "crm_companies": HelpinEndpointConfig(
        name="crm_companies",
        path="/crm/companies",
        data_selector="data.companies",
        primary_keys=["company_id"],
        scope="helpin.crm.read",
        incremental_fields=_UPDATED_AT,
        default_incremental_field="updated_at",
        updated_filter="crm_filter",
    ),
    "crm_deals": HelpinEndpointConfig(
        name="crm_deals",
        path="/crm/deals",
        data_selector="data.deals",
        primary_keys=["id"],
        scope="helpin.crm.read",
        page_size=50,
    ),
    "crm_pipelines": HelpinEndpointConfig(
        name="crm_pipelines",
        path="/crm/pipelines",
        data_selector="data.pipelines",
        primary_keys=["id"],
        scope="helpin.crm.read",
        pagination="single",
    ),
    "tasks": HelpinEndpointConfig(
        name="tasks",
        path="/tasks",
        data_selector="data.tasks",
        primary_keys=["task_id"],
        scope="helpin.pm.read",
        # The list leaves out archived tasks unless asked, and one call cannot return both kinds.
        passes=({"archived": "false"}, {"archived": "true"}),
        incremental_fields=_UPDATED_AT,
        default_incremental_field="updated_at",
        updated_filter="updated_after",
    ),
    "epics": HelpinEndpointConfig(
        name="epics",
        path="/epics",
        data_selector="data.epics",
        primary_keys=["epic_id"],
        scope="helpin.pm.read",
    ),
    "sprints": HelpinEndpointConfig(
        name="sprints",
        path="/sprints",
        data_selector="data.sprints",
        primary_keys=["id"],
        scope="helpin.pm.read",
    ),
    "objectives": HelpinEndpointConfig(
        name="objectives",
        path="/objectives",
        data_selector="data.objectives",
        primary_keys=["objective_id"],
        scope="helpin.pm.read",
    ),
    "labels": HelpinEndpointConfig(
        name="labels",
        path="/labels",
        data_selector="data.labels",
        primary_keys=["label_id"],
        scope="helpin.pm.read",
    ),
    "workflows": HelpinEndpointConfig(
        name="workflows",
        path="/workflows",
        data_selector="data.workflows",
        # One row per team: the workflow the team resolves to, with its states.
        primary_keys=["team_id"],
        scope="helpin.pm.read",
    ),
    "teams": HelpinEndpointConfig(
        name="teams",
        path="/teams",
        data_selector="data.teams",
        primary_keys=["id"],
        scope="helpin.context.read",
    ),
    "members": HelpinEndpointConfig(
        name="members",
        path="/members",
        data_selector="data.members",
        primary_keys=["member_id"],
        scope="helpin.context.read",
    ),
    "documents": HelpinEndpointConfig(
        name="documents",
        path="/documents",
        data_selector="data.documents",
        primary_keys=["document_id"],
        scope="helpin.docs.read",
        # Archived documents are left out unless asked.
        params={"include_archived": "true"},
    ),
}

ENDPOINTS = tuple(HELPIN_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HELPIN_ENDPOINTS.items()
}
