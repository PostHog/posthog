from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
    SortMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

SPACELIFT_HOST_TEMPLATE = "https://{account_name}.app.spacelift.io/graphql"
SPACELIFT_PAGE_SIZE = 100

CREATED_AT = "createdAt"

# Runs mutate after creation (queued -> in progress -> finished/failed) but the only
# server-side filter Spacelift's search API supports is a time range on `createdAt`,
# so incremental syncs re-pull a trailing window and let the delta merge collapse
# state changes onto the primary key. Runs typically settle within hours; a week
# covers long-lived approvals and drift-detection reruns without re-reading history.
RUNS_INCREMENTAL_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

INCREMENTAL_CREATED_AT_FIELDS: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.Integer,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass
class SpaceliftEndpointConfig:
    name: str
    # Top-level GraphQL field, e.g. "searchStacks". Fields prefixed "search" are
    # Relay-style connections taking a `SearchInput!`; anything else is a plain
    # list query with no pagination (e.g. "spaces").
    graphql_field: str
    # GraphQL selection set for one row (the connection node or list element).
    node_selection: str
    is_connection: bool = True
    # searchRuns nodes are `RunWithStack { run {...} stack {...} }` rather than a
    # flat object; the transport flattens them into run rows with stack context.
    flatten_run_with_stack: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Rows per page. Most connections accept 100; searchModules rejects anything over 50.
    page_size: int = SPACELIFT_PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    sort_mode: SortMode = "asc"


# Field selections verified against the live Spacelift GraphQL schema (validation-level,
# unauthenticated). Timestamps (`createdAt`, `updatedAt`, ...) are Unix epoch seconds (Int).
STACK_SELECTION = """
id
name
administrative
apiHost
branch
createdAt
deleted
deleting
description
isDrifted
labels
lockedAt
lockedBy
managesStateFile
namespace
projectRoot
provider
repository
repositoryURL
space
state
stateSetAt
terraformVersion
vcsDetached
"""

RUN_SELECTION = """
id
branch
commit {
    authorLogin
    authorName
    hash
    message
    timestamp
    url
}
createdAt
updatedAt
delta {
    addCount
    changeCount
    deleteCount
    resources
}
driftDetection
expired
finished
needsApproval
state
title
triggeredBy
type
"""

POLICY_SELECTION = """
id
name
description
type
body
space
labels
createdAt
updatedAt
"""

CONTEXT_SELECTION = """
id
name
description
space
labels
createdAt
updatedAt
"""

MODULE_SELECTION = """
id
name
administrative
apiHost
branch
createdAt
current {
    id
    number
}
description
labels
namespace
ownerSubdomain
projectRoot
provider
public
repository
space
terraformProvider
workflowTool
"""

WORKER_POOL_SELECTION = """
id
name
description
space
labels
createdAt
updatedAt
deleted
busyWorkers
pendingRuns
"""

SPACE_SELECTION = """
id
name
description
parentSpace
inheritEntities
labels
"""

MANAGED_ENTITY_SELECTION = """
id
address
name
type
parent
drifted
stackId
stackName
creator {
    id
}
updater {
    id
}
"""

SPACELIFT_ENDPOINTS: dict[str, SpaceliftEndpointConfig] = {
    "stacks": SpaceliftEndpointConfig(
        name="stacks",
        graphql_field="searchStacks",
        node_selection=STACK_SELECTION,
    ),
    # Account-wide across every stack and module, newest-first (the API's default
    # order; `orderBy` semantics aren't verifiable without credentials, so we rely
    # on the default and report sort_mode="desc" — the watermark then only persists
    # at successful job end, which is safe in either order).
    "runs": SpaceliftEndpointConfig(
        name="runs",
        graphql_field="searchRuns",
        node_selection=RUN_SELECTION,
        flatten_run_with_stack=True,
        incremental_fields=INCREMENTAL_CREATED_AT_FIELDS,
        partition_key=CREATED_AT,
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
    ),
    "policies": SpaceliftEndpointConfig(
        name="policies",
        graphql_field="searchPolicies",
        node_selection=POLICY_SELECTION,
    ),
    "contexts": SpaceliftEndpointConfig(
        name="contexts",
        graphql_field="searchContexts",
        node_selection=CONTEXT_SELECTION,
    ),
    "modules": SpaceliftEndpointConfig(
        name="modules",
        graphql_field="searchModules",
        node_selection=MODULE_SELECTION,
        page_size=50,
    ),
    "worker_pools": SpaceliftEndpointConfig(
        name="worker_pools",
        graphql_field="searchWorkerPools",
        node_selection=WORKER_POOL_SELECTION,
    ),
    "spaces": SpaceliftEndpointConfig(
        name="spaces",
        graphql_field="spaces",
        node_selection=SPACE_SELECTION,
        is_connection=False,
    ),
    # Terraform/OpenTofu resources tracked across stacks. Entity ids aren't documented
    # as globally unique, so the key includes the owning stack.
    "managed_entities": SpaceliftEndpointConfig(
        name="managed_entities",
        graphql_field="searchManagedEntities",
        node_selection=MANAGED_ENTITY_SELECTION,
        primary_keys=["stackId", "id"],
    ),
}

ENDPOINTS = tuple(SPACELIFT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPACELIFT_ENDPOINTS.items()
}
