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

EVENTS_QUERY = """
query PostHogGetEvents($first: Int!, $after: String, $startTime: DateTime, $descOrder: Boolean) {
  getEvents(first: $first, after: $after, startTime: $startTime, descOrder: $descOrder) {
    edges {
      node {
        uuid
        eventType
        eventState
        createdTime
        eventGeneratedTime
        description
        data
        importanceScore
        isImportant
        isChild
        isMerged
        monitorId
        parentMonitorId
        totalComments
        notifiedUsers
        customRuleEntities
        customRuleProjects
        customRuleDatasets
        ackTimestamp
        ackBy { email }
        alert { id }
        warehouse { uuid name }
        table { mcon fullTableId }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

DOMAINS_QUERY = """
query PostHogGetDomains($first: Int!, $after: String) {
  getDomainsV2(first: $first, after: $after) {
    edges {
      node {
        id
        uuid
        name
        description
        domainTag
        createdBy
        createdByEmail
        objAssignmentUpdateTime
        assignments
        excludedAssignments
        tags { name value }
        excludedTags { name value }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

DBT_RUNS_QUERY = """
query PostHogGetDbtRuns($first: Int!, $after: String) {
  getDbtRuns(first: $first, after: $after) {
    edges {
      node {
        id
        uuid
        dbtRunId
        createdTime
        updatedTime
        generatedAt
        startedAt
        command
        branch
        hasLogs
        dbtProject { uuid projectName }
        job { uuid jobId jobName mcon }
        jobExecution { uuid status startedAt finishedAt displayName }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

DBT_TEST_RESULTS_QUERY = """
query PostHogGetDbtTestResults($first: Int!, $after: String, $runStartTime: DateTime!, $runEndTime: DateTime!) {
  getDbtTestResults(first: $first, after: $after, runStartTime: $runStartTime, runEndTime: $runEndTime) {
    edges {
      node {
        runUuid
        nodeId
        nodeName
        runStartedAt
        startedAt
        executionTime
        status
        mcon
        jobName
        jobMcon
        command
        modelId
        modelName
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

MONITOR_UUIDS_QUERY = """
query PostHogGetMonitorUuids($limit: Int!, $offset: Int!, $monitorTypes: [UserDefinedMonitors]) {
  getMonitors(limit: $limit, offset: $offset, monitorTypes: $monitorTypes) {
    uuid
  }
}
"""

FH_EVENTS_QUERY = """
query PostHogGetFhEventsByMonitor($monitorId: UUID!, $startTime: DateTime!, $endTime: DateTime!, $first: Int!, $offset: Int!) {
  getFhEventsByMonitor(monitorId: $monitorId, startTime: $startTime, endTime: $endTime, first: $first, offset: $offset, descOrder: false) {
    events {
      eventUuid
      alertUuid
      eventType
      date
      metric
      field
      whereCondition
      value
      lowerThreshold
      upperThreshold
      thresholdType
      comparisonOperator
      autoOperator
      historicalMean
      aggTimeInterval
      customMetricDisplayName
      customMetricSqlExpression
      timeSeriesUuid
      parentTimeSeriesUuid
      detectorFeedback { id reason }
    }
  }
}
"""

JOB_EXECUTIONS_QUERY = """
query PostHogGetJobExecutions($monitorUuid: String!, $historyDays: Int!, $first: Int!, $after: String) {
  getJobExecutions(monitorUuid: $monitorUuid, historyDays: $historyDays, first: $first, after: $after) {
    edges {
      node {
        jobExecutionUuid
        startTime
        endTime
        status
        exceptions
        tableMonitorWarning
        sizeCollectionTableMcon
        sizeCollectionEnabled
        totalInvocationsCount
        totalResultCount
        totalExecutionDuration
        consolidatingJobUuid
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

JOB_SCHEDULES_QUERY = """
query PostHogGetJobSchedules($resourceUuid: String!) {
  getJobSchedules(resourceUuid: $resourceUuid) {
    uuid
    resourceId
    connectionId
    internalJobType
    limits
    intervalInSeconds
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
    "dbt_runs": MonteCarloEndpointConfig(
        name="dbt_runs",
        query=DBT_RUNS_QUERY,
        data_path="getDbtRuns",
        pagination="relay",
        primary_keys=["uuid"],
        partition_key="createdTime",
    ),
    "dbt_test_results": MonteCarloEndpointConfig(
        name="dbt_test_results",
        query=DBT_TEST_RESULTS_QUERY,
        data_path="getDbtTestResults",
        pagination="relay",
        # A dbt invocation runs each test node once, and results carry no id of their own.
        primary_keys=["runUuid", "nodeId"],
        default_incremental_field="runStartedAt",
        incremental_fields=[
            {
                "label": "runStartedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "runStartedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "domains": MonteCarloEndpointConfig(
        name="domains",
        query=DOMAINS_QUERY,
        data_path="getDomainsV2",
        pagination="relay",
        primary_keys=["id"],
    ),
    "events": MonteCarloEndpointConfig(
        name="events",
        query=EVENTS_QUERY,
        data_path="getEvents",
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
        ],
    ),
    "fh_events": MonteCarloEndpointConfig(
        name="fh_events",
        query=FH_EVENTS_QUERY,
        data_path="getFhEventsByMonitor",
        pagination="offset",
        primary_keys=["monitorUuid", "eventUuid"],
        default_incremental_field="date",
        partition_key="date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        page_size=1000,
    ),
    "job_executions": MonteCarloEndpointConfig(
        name="job_executions",
        query=JOB_EXECUTIONS_QUERY,
        data_path="getJobExecutions",
        pagination="relay",
        primary_keys=["monitorUuid", "jobExecutionUuid"],
        default_incremental_field="startTime",
        incremental_fields=[
            {
                "label": "startTime",
                "type": IncrementalFieldType.DateTime,
                "field": "startTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "job_schedules": MonteCarloEndpointConfig(
        name="job_schedules",
        query=JOB_SCHEDULES_QUERY,
        data_path="getJobSchedules",
        pagination="none",
        primary_keys=["uuid"],
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
