from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Doppler's documented default page size. The API docs don't state a maximum for `per_page`, so we
# stay at the documented default rather than risk a 400 on an unverified larger value.
DEFAULT_PER_PAGE = 20


def _created_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=True)
class DopplerEndpointConfig:
    name: str
    path: str  # Path under /v3, e.g. "/projects"
    # Root key of the list in the JSON response (e.g. `logs` for /v3/logs).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Endpoint accepts a `page` query param. Doppler's environments list takes no pagination
    # params at all and returns everything in one response.
    paginated: bool = True
    # `per_page` value to request. None for paginated endpoints that document no `per_page`
    # param (workplace users) — those terminate on the first empty page instead of a short one.
    per_page: Optional[int] = DEFAULT_PER_PAGE
    # Fan out one request-set per project: the endpoint requires a `project` query param.
    fan_out_over_projects: bool = False
    # Fan out one request-set per config: the endpoint requires both `project` and `config`.
    fan_out_over_configs: bool = False
    # Stamp the fanned-out project slug onto each row. Only for endpoints whose rows omit it —
    # most of Doppler's project-scoped responses already echo `project` back.
    inject_project: bool = False
    # The endpoint's responses contain plaintext secret values. Those are redacted out of the
    # rows before they are yielded, and the responses are kept out of HTTP sample capture,
    # whose name-based scrubbers cannot recognise a secret under a field named `added`.
    carries_secret_values: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. Only worthwhile for the (large, append-only)
    # log endpoints; the remaining endpoints are small dimension tables.
    partition_key: Optional[str] = None
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True
    description: Optional[str] = None


DOPPLER_ENDPOINTS: dict[str, DopplerEndpointConfig] = {
    "projects": DopplerEndpointConfig(
        name="projects",
        path="/projects",
        data_key="projects",
    ),
    "environments": DopplerEndpointConfig(
        name="environments",
        path="/environments",
        data_key="environments",
        # Environment ids ("dev", "stg", …) are only unique within their project.
        primary_keys=["project", "id"],
        paginated=False,
        per_page=None,
        fan_out_over_projects=True,
    ),
    "configs": DopplerEndpointConfig(
        name="configs",
        path="/configs",
        data_key="configs",
        # Configs have no id field; the name is unique within its project.
        primary_keys=["project", "name"],
        fan_out_over_projects=True,
    ),
    "activity_logs": DopplerEndpointConfig(
        name="activity_logs",
        path="/logs",
        data_key="logs",
        incremental_fields=_created_at_incremental_fields(),
        partition_key="created_at",
        # /v3/logs has no sort param and returns newest-first; incremental syncs stop paging once
        # a page reaches already-synced entries (see doppler.py).
        sort_mode="desc",
        description=(
            "Workplace activity log of project, config, and access changes. Incremental syncs "
            "stop paging once they reach already-synced entries."
        ),
    ),
    "workplace_users": DopplerEndpointConfig(
        name="workplace_users",
        path="/workplace/users",
        data_key="workplace_users",
        # The users list documents only a `page` param, no `per_page`.
        per_page=None,
    ),
    "groups": DopplerEndpointConfig(
        name="groups",
        path="/workplace/groups",
        data_key="groups",
        primary_keys=["slug"],
    ),
    "service_accounts": DopplerEndpointConfig(
        name="service_accounts",
        path="/workplace/service_accounts",
        data_key="service_accounts",
        primary_keys=["slug"],
    ),
    "invites": DopplerEndpointConfig(
        name="invites",
        path="/workplace/invites",
        data_key="invites",
        primary_keys=["slug"],
    ),
    "project_members": DopplerEndpointConfig(
        name="project_members",
        path="/projects/project/members",
        data_key="members",
        # Member rows carry no project field, so the fan-out stamps one on. Doppler addresses a
        # member by type and slug within a project, so all three make the row unique.
        primary_keys=["project", "type", "slug"],
        fan_out_over_projects=True,
        inject_project=True,
        description="Which workplace users, groups, service accounts, and invites can reach each project.",
    ),
    "project_roles": DopplerEndpointConfig(
        name="project_roles",
        path="/projects/roles",
        data_key="roles",
        primary_keys=["identifier"],
        paginated=False,
        per_page=None,
        description="Project role definitions, including the permissions each role grants.",
    ),
    "workplace_roles": DopplerEndpointConfig(
        name="workplace_roles",
        path="/workplace/roles",
        data_key="roles",
        primary_keys=["identifier"],
        paginated=False,
        per_page=None,
        description="Workplace role definitions, including the permissions each role grants.",
    ),
    "config_logs": DopplerEndpointConfig(
        name="config_logs",
        path="/configs/config/logs",
        data_key="logs",
        # Log ids are documented as unique per object, but this table pools every config's logs,
        # so keep the parents in the key rather than rely on that holding workplace-wide.
        primary_keys=["project", "config", "id"],
        fan_out_over_configs=True,
        carries_secret_values=True,
        partition_key="created_at",
        # One request-set per config, and the endpoint offers no time filter to narrow a re-sync,
        # so this stays off by default and is opted into deliberately.
        should_sync_default=False,
        description=(
            "Per-config change history of secret edits and rollbacks. This table syncs each config "
            "separately, so it takes longer than the others."
        ),
    ),
}

ENDPOINTS = tuple(DOPPLER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DOPPLER_ENDPOINTS.items()
}
