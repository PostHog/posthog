from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

RAILWAY_API_URL = "https://backboard.railway.com/graphql/v2"
# Railway doesn't document a hard max page size; dashboard queries use small values, so stay <= 100.
RAILWAY_PAGE_SIZE = 100

CREATED_AT = "createdAt"
# Synthesized on rows of the windowed `usage` and `metrics` tables, which carry no timestamp of their own.
DATE = "date"
TIMESTAMP = "timestamp"

INCREMENTAL_CREATED_AT: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]

INCREMENTAL_DATE: list[IncrementalField] = [
    {
        "label": DATE,
        "type": IncrementalFieldType.DateTime,
        "field": DATE,
        "field_type": IncrementalFieldType.DateTime,
    },
]

INCREMENTAL_TIMESTAMP: list[IncrementalField] = [
    {
        "label": TIMESTAMP,
        "type": IncrementalFieldType.DateTime,
        "field": TIMESTAMP,
        "field_type": IncrementalFieldType.DateTime,
    },
]

# `projectServiceUsage` caps `first` at 50 projects per page.
USAGE_PAGE_SIZE = 50
USAGE_INITIAL_LOOKBACK_DAYS = 90
# Railway keeps about 30 days of metrics, so an older start date returns nothing.
METRICS_INITIAL_LOOKBACK_DAYS = 30
METRICS_SAMPLE_RATE_SECONDS = 3600
METRICS_WINDOW_DAYS = 7

# The measurements Railway bills for: vCPU, memory, egress, volume storage and backups.
USAGE_MEASUREMENTS = ["CPU_USAGE", "MEMORY_USAGE_GB", "NETWORK_TX_GB", "DISK_USAGE_GB", "BACKUP_USAGE_GB"]
METRICS_MEASUREMENTS = [
    "CPU_USAGE",
    "CPU_LIMIT",
    "MEMORY_USAGE_GB",
    "MEMORY_LIMIT_GB",
    "NETWORK_RX_GB",
    "NETWORK_TX_GB",
    "DISK_USAGE_GB",
    "EPHEMERAL_DISK_USAGE_GB",
]

_PAGE_INFO = "pageInfo { hasNextPage endCursor }"

PROJECTS_QUERY = f"""
query Projects($first: Int!, $after: String) {{
  projects(first: $first, after: $after) {{
    edges {{
      node {{
        id
        name
        description
        isPublic
        isTempProject
        prDeploys
        botPrEnvironments
        workspaceId
        baseEnvironmentId
        primaryEnvironmentId
        createdAt
        updatedAt
        deletedAt
      }}
    }}
    {_PAGE_INFO}
  }}
}}
"""

SERVICES_QUERY = f"""
query ProjectServices($projectId: String!, $first: Int!, $after: String) {{
  project(id: $projectId) {{
    services(first: $first, after: $after) {{
      edges {{
        node {{
          id
          name
          icon
          projectId
          templateId
          templateServiceId
          createdAt
          updatedAt
          deletedAt
        }}
      }}
      {_PAGE_INFO}
    }}
  }}
}}
"""

ENVIRONMENTS_QUERY = f"""
query ProjectEnvironments($projectId: String!, $first: Int!, $after: String) {{
  environments(projectId: $projectId, first: $first, after: $after) {{
    edges {{
      node {{
        id
        name
        projectId
        isEphemeral
        unmergedChangesCount
        createdAt
        updatedAt
        deletedAt
      }}
    }}
    {_PAGE_INFO}
  }}
}}
"""

DEPLOYMENTS_QUERY = f"""
query ProjectDeployments($projectId: String!, $first: Int!, $after: String) {{
  deployments(input: {{ projectId: $projectId }}, first: $first, after: $after) {{
    edges {{
      node {{
        id
        status
        statusUpdatedAt
        projectId
        environmentId
        serviceId
        snapshotId
        staticUrl
        url
        meta
        deploymentStopped
        creator {{
          id
          name
          email
        }}
        createdAt
        updatedAt
      }}
    }}
    {_PAGE_INFO}
  }}
}}
"""

PROJECT_MEMBERS_QUERY = """
query ProjectMembers($projectId: String!) {
  projectMembers(projectId: $projectId) {
    id
    name
    email
    avatar
    role
  }
}
"""

VOLUMES_QUERY = f"""
query ProjectVolumes($projectId: String!, $first: Int!, $after: String) {{
  project(id: $projectId) {{
    volumes(first: $first, after: $after) {{
      edges {{
        node {{
          id
          name
          projectId
          createdAt
        }}
      }}
      {_PAGE_INFO}
    }}
  }}
}}
"""

EVENTS_QUERY = f"""
query ProjectEvents($projectId: String!, $first: Int!, $after: String) {{
  events(projectId: $projectId, first: $first, after: $after) {{
    edges {{
      node {{
        id
        action
        object
        severity
        projectId
        environmentId
        payload
        createdAt
      }}
    }}
    {_PAGE_INFO}
  }}
}}
"""

DEPLOYMENT_EVENTS_QUERY = f"""
query DeploymentEvents($deploymentId: String!, $first: Int!, $after: String) {{
  deploymentEvents(id: $deploymentId, first: $first, after: $after) {{
    edges {{
      node {{
        id
        step
        payload {{
          attempt
          maxAttempts
          durationMs
          skipped
          reason
          detail
          error
        }}
        createdAt
        completedAt
      }}
    }}
    {_PAGE_INFO}
  }}
}}
"""

USAGE_QUERY = """
query ProjectServiceUsage(
  $workspaceId: String!
  $startDate: DateTime!
  $endDate: DateTime!
  $measurements: [MetricMeasurement!]!
  $first: Int!
  $after: String
) {
  projectServiceUsage(
    workspaceId: $workspaceId
    startDate: $startDate
    endDate: $endDate
    measurements: $measurements
    includeDeleted: true
    first: $first
    after: $after
  ) {
    usage {
      measurement
      value
      tags {
        projectId
        serviceId
        environmentId
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ESTIMATED_USAGE_QUERY = """
query EstimatedUsage($workspaceId: String!, $measurements: [MetricMeasurement!]!) {
  estimatedUsage(workspaceId: $workspaceId, measurements: $measurements, includeDeleted: true) {
    projectId
    measurement
    estimatedValue
  }
}
"""

METRICS_QUERY = """
query ProjectMetrics(
  $projectId: String!
  $startDate: DateTime!
  $endDate: DateTime!
  $measurements: [MetricMeasurement!]!
  $sampleRateSeconds: Int!
) {
  metrics(
    projectId: $projectId
    startDate: $startDate
    endDate: $endDate
    measurements: $measurements
    groupBy: [SERVICE_ID, ENVIRONMENT_ID]
    sampleRateSeconds: $sampleRateSeconds
  ) {
    measurement
    tags {
      serviceId
      environmentId
    }
    values {
      ts
      value
    }
  }
}
"""

# Cheapest authenticated probe that works for both account and workspace tokens
# (workspace/team tokens cannot call `me`, so probe `projects` instead).
VALIDATION_QUERY = """
query ValidateToken {
  projects(first: 1) {
    edges {
      node {
        id
      }
    }
  }
}
"""


@dataclass
class RailwayEndpointConfig:
    name: str
    query: str
    # Path from the response `data` object down to the connection (or plain list) to read.
    data_path: tuple[str, ...]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_keys: list[str] | None = None
    # Whether the query pages a Relay connection (edges/pageInfo) vs returning a plain list.
    paginated: bool = True
    # Whether the endpoint runs once per project (projects are enumerated first).
    fan_out_over_projects: bool = True
    sort_mode: Literal["asc", "desc"] | None = "desc"
    # Overlap re-read on incremental syncs, for rows that keep changing after they are created.
    default_incremental_lookback_seconds: int | None = None


RAILWAY_ENDPOINTS: dict[str, RailwayEndpointConfig] = {
    "projects": RailwayEndpointConfig(
        name="projects",
        query=PROJECTS_QUERY,
        data_path=("projects",),
        fan_out_over_projects=False,
    ),
    "services": RailwayEndpointConfig(
        name="services",
        query=SERVICES_QUERY,
        data_path=("project", "services"),
    ),
    "environments": RailwayEndpointConfig(
        name="environments",
        query=ENVIRONMENTS_QUERY,
        data_path=("environments",),
    ),
    "deployments": RailwayEndpointConfig(
        name="deployments",
        query=DEPLOYMENTS_QUERY,
        data_path=("deployments",),
        incremental_fields=INCREMENTAL_CREATED_AT,
        partition_keys=[CREATED_AT],
        default_incremental_lookback_seconds=86400,
    ),
    "project_members": RailwayEndpointConfig(
        name="project_members",
        query=PROJECT_MEMBERS_QUERY,
        data_path=("projectMembers",),
        paginated=False,
        # Member ids are user ids, shared across projects — the project id must be in the key.
        primary_keys=["project_id", "id"],
    ),
    "volumes": RailwayEndpointConfig(
        name="volumes",
        query=VOLUMES_QUERY,
        data_path=("project", "volumes"),
    ),
    "events": RailwayEndpointConfig(
        name="events",
        query=EVENTS_QUERY,
        data_path=("events",),
        partition_keys=[CREATED_AT],
    ),
    "deployment_events": RailwayEndpointConfig(
        name="deployment_events",
        query=DEPLOYMENT_EVENTS_QUERY,
        data_path=("deploymentEvents",),
        incremental_fields=INCREMENTAL_CREATED_AT,
        # Deployment events carry no deployment id, so the transport adds one. Event ids are not
        # documented as globally unique, so the deployment id is part of the key.
        primary_keys=["deployment_id", "id"],
        partition_keys=[CREATED_AT],
        sort_mode=None,
        default_incremental_lookback_seconds=86400,
    ),
    "usage": RailwayEndpointConfig(
        name="usage",
        query=USAGE_QUERY,
        data_path=("projectServiceUsage",),
        incremental_fields=INCREMENTAL_DATE,
        partition_keys=[DATE],
        sort_mode=None,
    ),
    "estimated_usage": RailwayEndpointConfig(
        name="estimated_usage",
        query=ESTIMATED_USAGE_QUERY,
        data_path=("estimatedUsage",),
        paginated=False,
        primary_keys=["projectId", "measurement"],
        sort_mode=None,
    ),
    "metrics": RailwayEndpointConfig(
        name="metrics",
        query=METRICS_QUERY,
        data_path=("metrics",),
        paginated=False,
        incremental_fields=INCREMENTAL_TIMESTAMP,
        partition_keys=[TIMESTAMP],
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(RAILWAY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAILWAY_ENDPOINTS.items()
}
