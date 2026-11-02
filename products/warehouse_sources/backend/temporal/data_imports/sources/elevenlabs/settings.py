from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class ElevenLabsEndpointConfig:
    name: str
    # Path appended to ELEVENLABS_BASE_URL, including the API version (v1/v2 differ per endpoint).
    path: str
    # Top-level array key in the JSON response body (differs per endpoint: history/conversations/...).
    # A JSONPath such as "$.*" selects the values of a body keyed by id; None takes a bare-array body.
    items_key: Optional[str]
    # None for single-row snapshot tables that are replaced wholesale, so there is nothing to merge on.
    primary_keys: Optional[list[str]]
    # Query param used to request the next page, and the response field that carries the next cursor.
    # ElevenLabs uses three different cursor styles across endpoint families. Both None for
    # unpaginated endpoints that return the whole collection in one body.
    cursor_param: Optional[str] = None
    cursor_response_key: Optional[str] = None
    page_size: Optional[int] = None
    page_size_param: str = "page_size"
    # Set for endpoints paged by a 1-based page number instead of a cursor.
    page_number_param: Optional[str] = None
    # None for tables without a stable creation timestamp; those small tables stay unpartitioned.
    partition_key: Optional[str] = None
    # Stable, monotonic incremental column and the server-side filter param that bounds it. Both None
    # for full-refresh endpoints (agents/voices expose no updated-since filter).
    incremental_field: Optional[str] = None
    incremental_param: Optional[str] = None
    incremental_field_type: IncrementalFieldType = IncrementalFieldType.Integer
    # "asc" checkpoints the watermark after every batch; "desc" defers it to successful job end. Must
    # match the order rows actually arrive in for the endpoint.
    sort_mode: str = "asc"
    # Conversations are mutable (status/summary/sentiment fill in after the call), so they must merge
    # rather than append; immutable history items may append.
    supports_append: bool = False
    should_sync_default: bool = True
    # Constant query params merged into every request (sort direction, summary mode, ...).
    extra_params: dict[str, str] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.incremental_field:
            return []
        return [
            {
                "label": self.incremental_field,
                "type": self.incremental_field_type,
                "field": self.incremental_field,
                "field_type": self.incremental_field_type,
            }
        ]

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_field


ELEVENLABS_ENDPOINTS: dict[str, ElevenLabsEndpointConfig] = {
    # Text-to-speech / speech-to-speech generation history. Immutable per-generation records, filtered
    # server-side by `date_after_unix` (inclusive) and returned ascending via `sort_direction=asc`.
    "history": ElevenLabsEndpointConfig(
        name="history",
        path="/v1/history",
        items_key="history",
        cursor_param="start_after_history_item_id",
        cursor_response_key="last_history_item_id",
        primary_keys=["history_item_id"],
        page_size=1000,
        partition_key="date_unix",
        incremental_field="date_unix",
        incremental_param="date_after_unix",
        sort_mode="asc",
        supports_append=True,
        extra_params={"sort_direction": "asc"},
    ),
    # Conversational AI calls. Mutable (status transitions, transcript summary and sentiment land after
    # the call completes) so they merge, never append. Cursor pagination exposes no sort param; the
    # default is newest-first, so we report "desc" and let the server-side `call_start_after_unix`
    # filter bound the set on incremental runs. `summary_mode=include` pulls the summary/sentiment.
    "conversations": ElevenLabsEndpointConfig(
        name="conversations",
        path="/v1/convai/conversations",
        items_key="conversations",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["conversation_id"],
        page_size=100,
        partition_key="start_time_unix_secs",
        incremental_field="start_time_unix_secs",
        incremental_param="call_start_after_unix",
        sort_mode="desc",
        supports_append=False,
        extra_params={"summary_mode": "include"},
    ),
    # Conversational AI agent configs. Small, mutable table with no updated-since filter, so full
    # refresh only. Ordered ascending by creation for stable pagination.
    "agents": ElevenLabsEndpointConfig(
        name="agents",
        path="/v1/convai/agents",
        items_key="agents",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["agent_id"],
        page_size=100,
        partition_key="created_at_unix_secs",
        sort_mode="asc",
        extra_params={"sort_by": "created_at", "sort_direction": "asc"},
    ),
    # Voice library. Small, mutable table with no updated-since filter, so full refresh only. v2 uses a
    # `next_page_token` cursor; `created_at_unix` may be null for older voices (bucketed as epoch 0).
    "voices": ElevenLabsEndpointConfig(
        name="voices",
        path="/v2/voices",
        items_key="voices",
        cursor_param="next_page_token",
        cursor_response_key="next_page_token",
        primary_keys=["voice_id"],
        page_size=100,
        partition_key="created_at_unix",
        sort_mode="asc",
        extra_params={"sort": "created_at_unix", "sort_direction": "asc"},
    ),
    # Workspace-wide Conversational AI triage tickets. Mutable (status, priority, assignee, comments) with
    # no updated-since filter, so full refresh only. The API has no sort direction param and returns
    # newest-created first.
    "triage_tickets": ElevenLabsEndpointConfig(
        name="triage_tickets",
        path="/v1/convai/triage-tickets",
        items_key="agent_conversation_tickets",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["agentqa_ticket_id"],
        page_size=100,
        partition_key="created_at_unix_secs",
        sort_mode="desc",
        extra_params={"sort_by": "created_at"},
    ),
    # Model catalog that resolves the `model_id` on history items. Returned as one bare array.
    "models": ElevenLabsEndpointConfig(
        name="models",
        path="/v1/models",
        items_key=None,
        primary_keys=["model_id"],
    ),
    # Workspace members (service accounts excluded) that resolve user ids on history and conversations.
    # Returned as one bare array; needs the `workspace_members_read` permission.
    "workspace_members": ElevenLabsEndpointConfig(
        name="workspace_members",
        path="/v1/workspace/members",
        items_key=None,
        primary_keys=["user_id"],
    ),
    # Returned as one object keyed by group id, so the selector takes its values.
    "workspace_groups": ElevenLabsEndpointConfig(
        name="workspace_groups",
        path="/v1/workspace/groups",
        items_key="$.*",
        primary_keys=["id"],
    ),
    # Conversational AI tool catalog. Mutable with no updated-since filter and no top-level creation
    # timestamp, so full refresh and unpartitioned. Ordered ascending by creation for stable pagination.
    "tools": ElevenLabsEndpointConfig(
        name="tools",
        path="/v1/convai/tools",
        items_key="tools",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["id"],
        page_size=100,
        extra_params={"sort_by": "created_at", "sort_direction": "asc"},
    ),
    # Per-tool execution records, fanned out over `tools`. `start_time` (inclusive) bounds every page
    # server-side. The API documents no order, and rows from different tools interleave in time, so
    # "desc" defers the watermark to job end. `timestamp` is a float, which datetime partitioning
    # cannot bucket, so the table stays unpartitioned.
    "tool_executions": ElevenLabsEndpointConfig(
        name="tool_executions",
        path="/v1/convai/tools/{tool_id}/executions",
        items_key="executions",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["tool_id", "id"],
        page_size=100,
        incremental_field="timestamp",
        incremental_param="start_time",
        incremental_field_type=IncrementalFieldType.Numeric,
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="tools",
            resolve_param="tool_id",
            resolve_field="id",
            include_from_parent=[],
            parent_params={"sort_by": "created_at", "sort_direction": "asc"},
        ),
    ),
    # Phone numbers that Conversational AI agents take and place calls on. Returned as one bare array.
    "phone_numbers": ElevenLabsEndpointConfig(
        name="phone_numbers",
        path="/v1/convai/phone-numbers",
        items_key=None,
        primary_keys=["phone_number_id"],
    ),
    # Outbound batch calling jobs. Mutable (status and call counters change while the job runs) with no
    # updated-since filter, so full refresh only.
    "batch_calls": ElevenLabsEndpointConfig(
        name="batch_calls",
        path="/v1/convai/batch-calling/workspace",
        items_key="batch_calls",
        cursor_param="last_doc",
        cursor_response_key="next_doc",
        primary_keys=["id"],
        page_size=100,
        page_size_param="limit",
        partition_key="created_at_unix",
    ),
    # Traffic split history per agent, fanned out over `agents` and returned newest first. Rows carry no
    # agent id, so the parent id is copied in. No updated-since filter, so full refresh only.
    "agent_deployments": ElevenLabsEndpointConfig(
        name="agent_deployments",
        path="/v1/convai/agents/{agent_id}/deployments",
        items_key="results",
        page_number_param="page",
        primary_keys=["agent_id", "id"],
        page_size=100,
        partition_key="deployed_at_unix_secs",
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="agents",
            resolve_param="agent_id",
            resolve_field="agent_id",
            include_from_parent=["agent_id"],
            parent_field_renames={"agent_id": "agent_id"},
            parent_params={"sort_by": "created_at", "sort_direction": "asc"},
        ),
    ),
    # Published Flows templates. The API caps the page size at 25 because each row expands its versions'
    # input and output schemas. No creation timestamp, so the table stays unpartitioned.
    "flow_templates": ElevenLabsEndpointConfig(
        name="flow_templates",
        path="/v1/flows/templates",
        items_key="templates",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["id"],
        page_size=25,
    ),
    # Runs of each Flows template, fanned out over `flow_templates`. The API lists only runs created
    # through the API, newest first, with no timestamp or time filter, so full refresh and unpartitioned.
    "flow_template_runs": ElevenLabsEndpointConfig(
        name="flow_template_runs",
        path="/v1/flows/templates/{template_id}/runs",
        items_key="runs",
        cursor_param="cursor",
        cursor_response_key="next_cursor",
        primary_keys=["template_id", "id"],
        page_size=100,
        sort_mode="desc",
        fanout=DependentEndpointConfig(
            parent_name="flow_templates",
            resolve_param="template_id",
            resolve_field="id",
            include_from_parent=[],
            # The fan-out needs only template ids, so skip the extra version schemas.
            parent_params={"versions_per_template": 1},
        ),
    ),
    # Voice collections the key can access. Returned in one body sorted by title.
    "voice_collections": ElevenLabsEndpointConfig(
        name="voice_collections",
        path="/v1/voices/collections",
        items_key="collections",
        primary_keys=["collection_id"],
    ),
    # Plan quota and current-period usage, returned as one object that becomes a single row.
    "subscription": ElevenLabsEndpointConfig(
        name="subscription",
        path="/v1/user/subscription",
        items_key=None,
        primary_keys=None,
    ),
}

ENDPOINTS = tuple(ELEVENLABS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ELEVENLABS_ENDPOINTS.items()
}
