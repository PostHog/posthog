from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

RAILWAY_API_URL = "https://backboard.railway.com/graphql/v2"
# Railway doesn't document a hard max page size; dashboard queries use small values, so stay <= 100.
RAILWAY_PAGE_SIZE = 100

CREATED_AT = "createdAt"

INCREMENTAL_CREATED_AT: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
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
}

ENDPOINTS = tuple(RAILWAY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAILWAY_ENDPOINTS.items()
}
