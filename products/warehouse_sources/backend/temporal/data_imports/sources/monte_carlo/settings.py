from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Selection sets stick to fields verified against Monte Carlo's published GraphQL schema
# (the one bundled with their pycarlo SDK). Nested objects are limited to small, stable
# reference types so a schema change on a rich sub-object can't break the whole stream.

ALERTS_QUERY = """
query PostHogGetAlerts($first: Int!, $after: String, $createdTime: DateTimeRangeInput, $updatedTime: DateTimeRangeInput) {
  getAlerts(first: $first, after: $after, createdTime: $createdTime, updatedTime: $updatedTime) {
    edges {
      node {
        uuid
        title
        name
        type
        subTypes
        status
        severity
        priority
        triagePriority
        feedback
        createdTime
        updatedTime
        sloStatus
        sloType
        sloBreachedTime
        url
        commentCount
        lastCommentText
        invalidRows
        monitorUuids
        owner { email fullName }
        tables { mcon tableId isKeyAsset }
        assets { mcon assetId assetType }
        audiences { uuid label }
        monitorTags { name value }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

MONITORS_QUERY = """
query PostHogGetMonitors($limit: Int!, $offset: Int!) {
  getMonitors(limit: $limit, offset: $offset) {
    uuid
    monitorType
    udmType
    createdTime
    lastUpdateTime
    creatorId
    updaterId
    resourceId
    entities
    entityMcons
    entityCount
    scheduleType
    name
    ruleName
    description
    notes
    labels
    severity
    priority
    isSnoozeable
    isPaused
    isDraft
    isTemplateManaged
    namespace
    nextExecutionTime
    prevExecutionTime
    connectionId
    isOotbMonitor
    monitorRunStatus
    monitorStatus
    consolidatedMonitorStatus
    exceptions
  }
}
"""

TABLES_QUERY = """
query PostHogGetTables($first: Int!, $after: String) {
  getTables(first: $first, after: $after) {
    edges {
      node {
        id
        mcon
        tableId
        fullTableId
        discoveredTime
        friendlyName
        location
        projectName
        dataset
        description
        tableType
        isEncrypted
        createdTime
        lastModified
        viewIsMaterialized
        path
        priority
        tracked
        dynamicTable
        isDeleted
        deletedAt
        lastObserved
        isExcluded
        isMonitored
        dataProvider
        ingestType
        importanceScore
        isImportant
        lastActivity
        lastRead
        lastWrite
        lastVolumeChange
        warehouse { uuid name }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

USERS_QUERY = """
query PostHogGetUsers($first: Int!, $after: String) {
  getUsersInAccount(first: $first, after: $after) {
    edges {
      node {
        id
        cognitoUserId
        email
        firstName
        lastName
        displayName
        state
        createdOn
        isSso
        isDeleted
        deletedAt
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

WAREHOUSES_QUERY = """
query PostHogGetWarehouses {
  getWarehouses {
    uuid
    name
    connectionType
    createdTime
    updatedTime
    isDeleted
    deletedAt
    bqProjectId
  }
}
"""

VALIDATE_CREDENTIALS_QUERY = """
query PostHogValidateCredentials {
  getUser { email }
}
"""

PaginationStyle = Literal["relay", "offset", "none"]


@dataclass
class MonteCarloEndpointConfig:
    name: str
    query: str
    # Top-level query field the rows live under in the response `data` object.
    data_path: str
    pagination: PaginationStyle
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str = "createdTime"
    partition_key: Optional[str] = None
    page_size: int = 100


MONTE_CARLO_ENDPOINTS: dict[str, MonteCarloEndpointConfig] = {
    "alerts": MonteCarloEndpointConfig(
        name="alerts",
        query=ALERTS_QUERY,
        data_path="getAlerts",
        pagination="relay",
        primary_keys=["uuid"],
        partition_key="createdTime",
        incremental_fields=[
            {
                "label": "createdTime",
                "type": IncrementalFieldType.DateTime,
                "field": "createdTime",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "updatedTime",
                "type": IncrementalFieldType.DateTime,
                "field": "updatedTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "monitors": MonteCarloEndpointConfig(
        name="monitors",
        query=MONITORS_QUERY,
        data_path="getMonitors",
        pagination="offset",
        primary_keys=["uuid"],
    ),
    "tables": MonteCarloEndpointConfig(
        name="tables",
        query=TABLES_QUERY,
        data_path="getTables",
        pagination="relay",
        primary_keys=["id"],
    ),
    "users": MonteCarloEndpointConfig(
        name="users",
        query=USERS_QUERY,
        data_path="getUsersInAccount",
        pagination="relay",
        primary_keys=["id"],
    ),
    "warehouses": MonteCarloEndpointConfig(
        name="warehouses",
        query=WAREHOUSES_QUERY,
        data_path="getWarehouses",
        pagination="none",
        primary_keys=["uuid"],
    ),
}

ENDPOINTS = tuple(MONTE_CARLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MONTE_CARLO_ENDPOINTS.items()
}
