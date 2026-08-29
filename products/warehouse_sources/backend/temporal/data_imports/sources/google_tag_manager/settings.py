from dataclasses import dataclass, field
from typing import Literal

GoogleTagManagerParentLevel = Literal["root", "account", "container", "workspace"]


@dataclass(frozen=True)
class GoogleTagManagerEndpoint:
    """One GTM API v2 list endpoint. Non-root endpoints fan out per parent resource path."""

    name: str
    parent_level: GoogleTagManagerParentLevel
    path_suffix: str
    data_key: str
    description: str
    params: dict[str, str] = field(default_factory=dict)


# Every GTM resource carries `path`, its API relative path (e.g.
# "accounts/1/containers/2/workspaces/3/tags/4"). It is the only identifier that is unique
# across the whole table: bare ids like tagId are only unique within their parent workspace.
GOOGLE_TAG_MANAGER_PRIMARY_KEYS = ["path"]

ENDPOINTS: dict[str, GoogleTagManagerEndpoint] = {
    "accounts": GoogleTagManagerEndpoint(
        name="accounts",
        parent_level="root",
        path_suffix="accounts",
        data_key="account",
        description="Tag Manager accounts the connected Google user can access.",
    ),
    "containers": GoogleTagManagerEndpoint(
        name="containers",
        parent_level="account",
        path_suffix="containers",
        data_key="container",
        description="Containers in each account, with their public IDs, domains, and usage contexts.",
    ),
    "workspaces": GoogleTagManagerEndpoint(
        name="workspaces",
        parent_level="container",
        path_suffix="workspaces",
        data_key="workspace",
        description="Workspaces in each container.",
    ),
    "tags": GoogleTagManagerEndpoint(
        name="tags",
        parent_level="workspace",
        path_suffix="tags",
        data_key="tag",
        description="Tags in each workspace, with their type, parameters, and firing and blocking trigger IDs.",
    ),
    "triggers": GoogleTagManagerEndpoint(
        name="triggers",
        parent_level="workspace",
        path_suffix="triggers",
        data_key="trigger",
        description="Triggers in each workspace, with their type and filter conditions.",
    ),
    "variables": GoogleTagManagerEndpoint(
        name="variables",
        parent_level="workspace",
        path_suffix="variables",
        data_key="variable",
        description="Variables in each workspace, with their type and parameters.",
    ),
    "container_versions": GoogleTagManagerEndpoint(
        name="container_versions",
        parent_level="container",
        path_suffix="version_headers",
        data_key="containerVersionHeader",
        description="Version headers for each container, including deleted (archived) versions.",
        params={"includeDeleted": "true"},
    ),
}
