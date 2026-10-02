from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Devin (Cognition AI) v3 API. Every org-level list endpoint shares the same shape:
#   GET https://api.devin.ai/v3/organizations/{org_id}/<resource>
#   (members uses the v3beta1 org path, /v3beta1/organizations/{org_id}/members/users, with the
#   identical envelope and auth)
#   cursor pagination via `first` (<=200) / `after`, response envelope
#   {"items": [...], "end_cursor": str | None, "has_next_page": bool, "total": int | None}
# Timestamps (`created_at` / `updated_at`) are integer Unix seconds.
#
# The consumption endpoints are the exception: they answer with a single unpaginated
# {"total_acus": float, "consumption_by_date": [...]} object, so they select a different key and
# take no page-size param.
#
# The v3 sessions endpoint documents server-side `created_after` / `updated_after` filters that could
# power incremental sync, but we can't verify against the live API (no credentials), and the default
# result ordering is undocumented. Declaring incremental with the wrong sort assumption corrupts the
# watermark, so every endpoint ships full-refresh-only for now. Cursor pagination still makes the sync
# resumable across heartbeat timeouts. Enabling incremental on sessions is a follow-up once the filter
# and ordering are curl-verified.

# v3 cursor pagination caps `first` at 200.
PAGE_SIZE = 200


@dataclass(frozen=True)
class DevinAIEndpointConfig:
    name: str
    # Path template under the API root; `{org_id}` is filled from the source config. A fan-out child
    # keeps its parent placeholder (e.g. `{devin_id}`) for the fan-out helper to bind per parent row.
    path: str
    # Field to partition Delta files by. Must be a STABLE field (created_at, never updated_at).
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Key in the response body holding the rows.
    data_selector: str = "items"
    # False for the consumption endpoints, which return their whole collection in one response.
    paginated: bool = True
    page_size: int = PAGE_SIZE
    # Endpoint to probe when validating credentials for this table. A fan-out child needs a parent id
    # in its path, so it delegates to the org-level endpoint gated by the same permission.
    probe_endpoint: Optional[str] = None
    # Path fan-out driven by the shared rest_source helper (parent id fills a {placeholder}).
    fanout: Optional[DependentEndpointConfig] = None
    # Full refresh only — kept so the config satisfies the fan-out helper's protocol.
    default_incremental_field: Optional[str] = None


DEVIN_AI_ENDPOINTS: dict[str, DevinAIEndpointConfig] = {
    "sessions": DevinAIEndpointConfig(
        name="sessions",
        path="/v3/organizations/{org_id}/sessions",
        primary_keys=["session_id"],
    ),
    # Same session records as `sessions` plus Devin's own quality read on each run: message counts,
    # session size band, and the generated analysis with its status.
    "session_insights": DevinAIEndpointConfig(
        name="session_insights",
        path="/v3/organizations/{org_id}/sessions/insights",
        primary_keys=["session_id"],
    ),
    # The conversation inside a session, one request per session. Off by default because the request
    # count grows with the org's whole session history, and most orgs only want the session rows.
    "session_messages": DevinAIEndpointConfig(
        name="session_messages",
        path="/v3/organizations/{org_id}/sessions/{devin_id}/messages",
        # event_id is documented as the message id, with no promise of uniqueness beyond its session,
        # so the parent session scopes the key.
        primary_keys=["session_id", "event_id"],
        should_sync_default=False,
        probe_endpoint="sessions",
        fanout=DependentEndpointConfig(
            parent_name="sessions",
            resolve_param="devin_id",
            resolve_field="session_id",
            # Message rows carry no session id, so copy the parent's down as `session_id`.
            include_from_parent=["session_id"],
            parent_field_renames={"session_id": "session_id"},
        ),
    ),
    "playbooks": DevinAIEndpointConfig(
        name="playbooks",
        path="/v3/organizations/{org_id}/playbooks",
        primary_keys=["playbook_id"],
    ),
    "knowledge_notes": DevinAIEndpointConfig(
        name="knowledge_notes",
        path="/v3/organizations/{org_id}/knowledge/notes",
        primary_keys=["note_id"],
    ),
    # Org members, carrying user_id + email so the opaque user_id on sessions resolves to a person.
    # Backed by the v3beta1 org-scoped users listing (needs the org-level `ViewOrgMembership`
    # permission): the stable alternatives require credentials this source doesn't store (the v2
    # members endpoint takes only enterprise-admin personal `apk_user_*` keys, and the v3 enterprise
    # listing needs an enterprise-level service user). Member records carry no created_at, so the
    # table declares no partition key, and the list is small and slow-changing, so full refresh only.
    "members": DevinAIEndpointConfig(
        name="members",
        path="/v3beta1/organizations/{org_id}/members/users",
        partition_key=None,
        primary_keys=["user_id"],
    ),
    # Org-wide ACU spend per day. One row per day, so full refresh stays cheap.
    "consumption_daily": DevinAIEndpointConfig(
        name="consumption_daily",
        path="/v3/organizations/{org_id}/consumption/daily",
        partition_key="date",
        primary_keys=["date"],
        data_selector="consumption_by_date",
        paginated=False,
    ),
    # The same daily spend split per member, so ACUs can be attributed to a person.
    "consumption_daily_users": DevinAIEndpointConfig(
        name="consumption_daily_users",
        path="/v3/organizations/{org_id}/consumption/daily/users/{user_id}",
        partition_key="date",
        primary_keys=["user_id", "date"],
        data_selector="consumption_by_date",
        paginated=False,
        probe_endpoint="consumption_daily",
        fanout=DependentEndpointConfig(
            parent_name="members",
            resolve_param="user_id",
            resolve_field="user_id",
            # Consumption rows are just date + ACUs, so the member they belong to comes from the parent.
            include_from_parent=["user_id"],
            parent_field_renames={"user_id": "user_id"},
        ),
    ),
    # Org secrets expose metadata only (key names, type, audit fields) — never the secret values.
    # Off by default so a user opts in rather than silently syncing secret metadata.
    "secrets": DevinAIEndpointConfig(
        name="secrets",
        path="/v3/organizations/{org_id}/secrets",
        primary_keys=["secret_id"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(DEVIN_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DEVIN_AI_ENDPOINTS.items()
}
