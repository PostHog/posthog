from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Devin (Cognition AI) v3 API. Every org-level list endpoint shares the same shape:
#   GET https://api.devin.ai/v3/organizations/{org_id}/<resource>
#   cursor pagination via `first` (<=200) / `after`, response envelope
#   {"items": [...], "end_cursor": str | None, "has_next_page": bool, "total": int | None}
# Timestamps (`created_at` / `updated_at`) are integer Unix seconds.
#
# The v3 sessions endpoint documents server-side `created_after` / `updated_after` filters that could
# power incremental sync, but we can't verify against the live API (no credentials), and the default
# result ordering is undocumented. Declaring incremental with the wrong sort assumption corrupts the
# watermark, so every endpoint ships full-refresh-only for now. Cursor pagination still makes the sync
# resumable across heartbeat timeouts. Enabling incremental on sessions is a follow-up once the filter
# and ordering are curl-verified.


@dataclass
class DevinAIEndpointConfig:
    name: str
    # Path template under the API root; `{org_id}` is filled from the source config.
    path: str
    # Field to partition Delta files by. Must be a STABLE field (created_at, never updated_at).
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


DEVIN_AI_ENDPOINTS: dict[str, DevinAIEndpointConfig] = {
    "sessions": DevinAIEndpointConfig(
        name="sessions",
        path="/v3/organizations/{org_id}/sessions",
        primary_keys=["session_id"],
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
