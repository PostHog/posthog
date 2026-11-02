from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

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


@dataclass
class SalesloftEndpointConfig:
    name: str
    path: str
    incremental: bool = False
    partition_key: Optional[str] = None

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


def _incremental(name: str, path: str) -> SalesloftEndpointConfig:
    return SalesloftEndpointConfig(name=name, path=path, incremental=True, partition_key="created_at")


def _full_refresh(name: str, path: str, partition_key: Optional[str] = "created_at") -> SalesloftEndpointConfig:
    return SalesloftEndpointConfig(name=name, path=path, incremental=False, partition_key=partition_key)


SALESLOFT_ENDPOINTS: dict[str, SalesloftEndpointConfig] = {
    # Incremental (server-side `updated_at[gte]` filter, ascending `updated_at` order)
    "accounts": _incremental("accounts", "/accounts"),
    "account_stages": _incremental("account_stages", "/account_stages"),
    "actions": _incremental("actions", "/actions"),
    "cadences": _incremental("cadences", "/cadences"),
    "cadence_memberships": _incremental("cadence_memberships", "/cadence_memberships"),
    "call_data_records": _incremental("call_data_records", "/call_data_records"),
    "calls": _incremental("calls", "/activities/calls"),
    "crm_activities": _incremental("crm_activities", "/crm_activities"),
    "emails": _incremental("emails", "/activities/emails"),
    "email_templates": _incremental("email_templates", "/email_templates"),
    "notes": _incremental("notes", "/notes"),
    "people": _incremental("people", "/people"),
    "successes": _incremental("successes", "/successes"),
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
    "team_template_attachments": _full_refresh(
        "team_template_attachments", "/team_template_attachments", partition_key=None
    ),
    "users": _full_refresh("users", "/users"),
}

ENDPOINTS = tuple(SALESLOFT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SALESLOFT_ENDPOINTS.items()
}
