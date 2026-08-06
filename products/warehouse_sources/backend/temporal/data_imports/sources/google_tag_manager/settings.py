from typing import Literal, TypedDict

# Google Tag Manager API v2 organizes everything under an account:
#   account -> containers -> workspaces -> {tags, triggers, variables}
#             (containers also own version headers)
# The user picks one account, and every table below is scoped to it. Each GTM
# resource carries a globally-unique `path` (e.g.
# `accounts/123/containers/456/workspaces/7/tags/8`), so `path` is the primary key
# for every table.

Grain = Literal["account", "container", "workspace"]


class GTMSchema(TypedDict):
    # Which level of the hierarchy the resource lives at. `account` resources are
    # fetched once, `container` resources fan out per container, and `workspace`
    # resources fan out per container per workspace.
    grain: Grain
    # Path segment appended to the parent resource's `path` to reach the list
    # endpoint. Empty for the single-object account endpoint.
    path_suffix: str
    # JSON key wrapping the returned list. Empty when the endpoint returns a single
    # object (the account itself) rather than a list.
    response_key: str
    primary_key: list[str]
    should_sync_default: bool
    description: str


GTM_SCHEMAS: dict[str, GTMSchema] = {
    "accounts": {
        "grain": "account",
        "path_suffix": "",
        "response_key": "",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": "The connected Tag Manager account, including its name and sharing settings.",
    },
    "containers": {
        "grain": "account",
        "path_suffix": "containers",
        "response_key": "container",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": (
            "Every container in the account, each holding the tags, triggers, and variables for one "
            "website or app, with its public id and usage context."
        ),
    },
    "workspaces": {
        "grain": "container",
        "path_suffix": "workspaces",
        "response_key": "workspace",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": "Workspaces across every container — the editable drafts where container changes are staged.",
    },
    "tags": {
        "grain": "workspace",
        "path_suffix": "tags",
        "response_key": "tag",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": (
            "Tags across every workspace, including type, firing and blocking triggers, and configuration parameters."
        ),
    },
    "triggers": {
        "grain": "workspace",
        "path_suffix": "triggers",
        "response_key": "trigger",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": "Triggers across every workspace — the conditions that fire or block tags.",
    },
    "variables": {
        "grain": "workspace",
        "path_suffix": "variables",
        "response_key": "variable",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": "User-defined variables across every workspace, including type and configuration parameters.",
    },
    "container_versions": {
        "grain": "container",
        "path_suffix": "version_headers",
        "response_key": "containerVersionHeader",
        "primary_key": ["path"],
        "should_sync_default": True,
        "description": (
            "Version headers for every container — one row per saved container version, with its element "
            "counts and deletion status."
        ),
    },
}
