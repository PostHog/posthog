from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

# Salesloft v2 resources. Endpoint set + incremental support mirror the canonical
# Airbyte connector (`source-salesloft`), which is the authoritative reference for
# which list endpoints actually honour the server-side `updated_at[gte]` filter.
#
# `incremental=True` is only set where Salesloft documents (and Airbyte uses) the
# `updated_at` range filter together with `sort_direction=ASC` (default sort key is
# `updated_at` on those endpoints). Everything else ships full-refresh only.
#
# Partition key is always the STABLE `created_at` field, set only on resources whose
# payload actually carries `created_at` (some join/attachment resources do not).

SALESLOFT_UPDATED_AT_FIELD = "updated_at"
# Salesloft caps per_page at 100; larger pages keep us under the per-page rate-limit
# cost penalties that escalate past page 100.
PAGE_SIZE = 100


@dataclass(frozen=False)
class SalesloftEndpointConfig:
    name: str
    path: str
    incremental: bool = False
    partition_key: Optional[str] = None
    # Set where the endpoint's default `sort_by` is not `updated_at` (tasks, activity_histories).
    sort_by: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE

    @property
    def default_incremental_field(self) -> Optional[str]:
        return SALESLOFT_UPDATED_AT_FIELD if self.incremental else None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.incremental:
            return []
        return [
            {
                "label": SALESLOFT_UPDATED_AT_FIELD,
                "type": IncrementalFieldType.DateTime,
                "field": SALESLOFT_UPDATED_AT_FIELD,
                "field_type": IncrementalFieldType.DateTime,
            }
        ]


def _incremental(name: str, path: str, sort_by: Optional[str] = None) -> SalesloftEndpointConfig:
    return SalesloftEndpointConfig(name=name, path=path, incremental=True, partition_key="created_at", sort_by=sort_by)


def _full_refresh(name: str, path: str, partition_key: Optional[str] = "created_at") -> SalesloftEndpointConfig:
    return SalesloftEndpointConfig(name=name, path=path, incremental=False, partition_key=partition_key)


SALESLOFT_ENDPOINTS: dict[str, SalesloftEndpointConfig] = {
    # Incremental (server-side `updated_at[gte]` filter, ascending `updated_at` order)
    "accounts": _incremental("accounts", "/accounts"),
    "account_stages": _incremental("account_stages", "/account_stages"),
    "actions": _incremental("actions", "/actions"),
    "activity_histories": _incremental("activity_histories", "/activity_histories", sort_by="updated_at"),
    "cadences": _incremental("cadences", "/cadences"),
    "cadence_memberships": _incremental("cadence_memberships", "/cadence_memberships"),
    "call_data_records": _incremental("call_data_records", "/call_data_records"),
    "calls": _incremental("calls", "/activities/calls"),
    "crm_activities": _incremental("crm_activities", "/crm_activities"),
    "emails": _incremental("emails", "/activities/emails"),
    "email_templates": _incremental("email_templates", "/email_templates"),
    "notes": _incremental("notes", "/notes"),
    "opportunities": _incremental("opportunities", "/opportunities", sort_by="updated_at"),
    "opportunity_people": _incremental("opportunity_people", "/opportunity_people"),
    "opportunity_stages": _incremental("opportunity_stages", "/opportunity_stages"),
    "people": _incremental("people", "/people"),
    "successes": _incremental("successes", "/successes"),
    "tasks": _incremental("tasks", "/tasks", sort_by="updated_at"),
    "team_templates": _incremental("team_templates", "/team_templates"),
    # Full refresh (no reliable server-side timestamp filter; mostly reference/config data)
    "account_tiers": _full_refresh("account_tiers", "/account_tiers"),
    "call_dispositions": _full_refresh("call_dispositions", "/call_dispositions"),
    "call_sentiments": _full_refresh("call_sentiments", "/call_sentiments"),
    "crm_users": _full_refresh("crm_users", "/crm_users"),
    "custom_fields": _full_refresh("custom_fields", "/custom_fields"),
    "email_template_attachments": _full_refresh(
        "email_template_attachments", "/email_template_attachments", partition_key=None
    ),
    "groups": _full_refresh("groups", "/groups", partition_key=None),
    "imports": _full_refresh("imports", "/imports"),
    "meetings": _full_refresh("meetings", "/meetings"),
    "person_stages": _full_refresh("person_stages", "/person_stages"),
    "phone_number_assignments": _full_refresh(
        "phone_number_assignments", "/phone_number_assignments", partition_key=None
    ),
    "steps": _full_refresh("steps", "/steps"),
    "tags": _full_refresh("tags", "/tags", partition_key=None),
    "team_template_attachments": _full_refresh(
        "team_template_attachments", "/team_template_attachments", partition_key=None
    ),
    "users": _full_refresh("users", "/users"),
    # Fan-out: Salesloft serves cadence stats one cadence at a time (`/cadence_stats/{id}`), and the
    # payload carries no cadence id, so the parent id is injected as `cadence_id`.
    "cadence_stats": SalesloftEndpointConfig(
        name="cadence_stats",
        path="/cadence_stats/{cadence_id}",
        primary_keys=["cadence_id"],
        fanout=DependentEndpointConfig(
            parent_name="cadences",
            resolve_param="cadence_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "cadence_id"},
            # A stable sort keeps page boundaries fixed while cadences are added during the walk.
            parent_params={"per_page": PAGE_SIZE, "sort_by": "created_at", "sort_direction": "ASC"},
            # A cadence deleted between the listing and its stats fetch 404s; skip it.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(SALESLOFT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SALESLOFT_ENDPOINTS.items()
}
