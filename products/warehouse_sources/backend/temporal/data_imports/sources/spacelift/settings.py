from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
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
# Audit entries never change, so the overlap only covers entries written in the same
# second as the last synced one while the previous sync was reading.
AUDIT_TRAIL_INCREMENTAL_LOOKBACK_SECONDS = 60 * 60

RUN_CREATED_AT = "runCreatedAt"
TIMESTAMP = "timestamp"

INCREMENTAL_CREATED_AT_FIELDS: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.Integer,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.Integer,
    },
]

INCREMENTAL_RUN_CREATED_AT_FIELDS: list[IncrementalField] = [
    {
        "label": RUN_CREATED_AT,
        "type": IncrementalFieldType.Integer,
        "field": RUN_CREATED_AT,
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass(frozen=True)
class SpaceliftParentConfig:
    # Connection that lists the parents, e.g. "searchModules".
    search_field: str
    # Single-object query field that scopes the child connection, e.g. "module".
    lookup_field: str
    # Row column the parent's id is written to.
    id_column: str
    page_size: int = SPACELIFT_PAGE_SIZE


@dataclass(frozen=True)
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
    # Child connections (e.g. a module's versions) are queried once per parent row.
    parent: SpaceliftParentConfig | None = None
    # Per-resource changes are selected inside searchRuns and flattened to one row per change.
    flatten_run_changes: bool = False
    order_by: dict[str, str] | None = None
    # API field the incremental predicate filters on, when the row column has another name.
    incremental_predicate_field: str | None = None
    incremental_lookback_seconds: int = RUNS_INCREMENTAL_LOOKBACK_SECONDS
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Rows per page. Most connections accept 100; searchModules, searchModuleVersions,
    # searchEvaluationRecords and searchAuditTrailEntries reject anything over 50.
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

AUDIT_TRAIL_ENTRY_SELECTION = """
id
action
eventType
body
createdAt
updatedAt
remoteIP
identityUlid
actor {
    username
    run {
        id
        stackId
    }
}
affectedResource {
    resourceType
    resourceId
}
relatedResource {
    resourceType
    resourceId
}
"""

# Selected under each searchRuns node as `run { id createdAt changesV2(...) { ... } }`.
# changesV2 works for every vendor; changesV3 and searchEntityChanges error outside Terraform.
RUN_CHANGE_SELECTION = """
type
phase
entity {
    id
    address
    name
    type
    parent
}
"""
RUN_CHANGES_PAGE_SIZE = 50

POLICY_EVALUATION_RECORD_SELECTION = """
key
outcome
timestamp
"""

MODULE_VERSION_SELECTION = """
id
number
state
createdAt
lastPulledAt
triggeredBy
sourceURL
downloadLink
notes
yanked
yankedBy
yankNote
consumerCount
versionCount
commit {
    authorLogin
    authorName
    hash
    message
    timestamp
    url
}
module {
    id
    name
    owner
}
consumers {
    id
}
"""

CREATED_AT_DESC = {"field": CREATED_AT, "direction": "DESC"}

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
    "audit_trail_entries": SpaceliftEndpointConfig(
        name="audit_trail_entries",
        graphql_field="searchAuditTrailEntries",
        node_selection=AUDIT_TRAIL_ENTRY_SELECTION,
        page_size=50,
        order_by=CREATED_AT_DESC,
        incremental_fields=INCREMENTAL_CREATED_AT_FIELDS,
        incremental_lookback_seconds=AUDIT_TRAIL_INCREMENTAL_LOOKBACK_SECONDS,
        partition_key=CREATED_AT,
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
    ),
    # One row per resource change of each run. Changes appear once a run plans or applies,
    # so incremental syncs re-read the same trailing window of runs as the runs table.
    "run_changes": SpaceliftEndpointConfig(
        name="run_changes",
        graphql_field="searchRuns",
        node_selection=RUN_CHANGE_SELECTION,
        flatten_run_changes=True,
        # Each run in the page carries up to RUN_CHANGES_PAGE_SIZE nested changes.
        page_size=20,
        primary_keys=["runId", "phase", "address"],
        incremental_fields=INCREMENTAL_RUN_CREATED_AT_FIELDS,
        incremental_predicate_field=CREATED_AT,
        partition_key=RUN_CREATED_AT,
        partition_mode="datetime",
        partition_format="month",
        sort_mode="desc",
    ),
    "policy_evaluation_records": SpaceliftEndpointConfig(
        name="policy_evaluation_records",
        graphql_field="searchEvaluationRecords",
        node_selection=POLICY_EVALUATION_RECORD_SELECTION,
        parent=SpaceliftParentConfig(search_field="searchPolicies", lookup_field="policy", id_column="policyId"),
        page_size=50,
        primary_keys=["policyId", "key"],
        partition_key=TIMESTAMP,
        partition_mode="datetime",
        partition_format="month",
    ),
    "module_versions": SpaceliftEndpointConfig(
        name="module_versions",
        graphql_field="searchModuleVersions",
        node_selection=MODULE_VERSION_SELECTION,
        parent=SpaceliftParentConfig(
            search_field="searchModules", lookup_field="module", id_column="moduleId", page_size=50
        ),
        page_size=50,
        order_by=CREATED_AT_DESC,
        primary_keys=["moduleId", "id"],
        partition_key=CREATED_AT,
        partition_mode="datetime",
        partition_format="month",
    ),
}

ENDPOINTS = tuple(SPACELIFT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPACELIFT_ENDPOINTS.items()
}
