from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Field selections stick to long-stable parts of the Sourcegraph GraphQL schema so the same
# query validates on older self-hosted instances, not just sourcegraph.com.
REPOSITORIES_QUERY = """
query Repositories($first: Int!, $after: String) {
  repositories(first: $first, after: $after, orderBy: REPOSITORY_CREATED_AT, descending: false) {
    nodes {
      id
      databaseID
      name
      description
      language
      createdAt
      updatedAt
      isPrivate
      isFork
      isArchived
      stars
      url
      externalRepository {
        serviceType
        serviceID
      }
      defaultBranch {
        name
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

USERS_QUERY = """
query Users($first: Int!, $after: String) {
  users(first: $first, after: $after) {
    nodes {
      id
      username
      displayName
      avatarURL
      url
      createdAt
      updatedAt
      siteAdmin
      builtinAuth
      emails {
        email
        isPrimary
        verified
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

# The organizations connection has no cursor (nodes + totalCount only), so it is fetched as a
# single capped request — see UNPAGINATED_FETCH_LIMIT in sourcegraph.py.
ORGANIZATIONS_QUERY = """
query Organizations($first: Int!) {
  organizations(first: $first) {
    nodes {
      id
      name
      displayName
      createdAt
      url
    }
    totalCount
  }
}
"""


@dataclass
class SourcegraphEndpointConfig:
    name: str
    query: str
    # Top-level key under `data` holding the connection (e.g. "repositories").
    data_path: str
    # None of the connections expose a server-side updated-since filter, so every endpoint is
    # full-refresh only; the list stays as the declarative menu should Sourcegraph add one.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by. Never updatedAt (it mutates).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = 100
    # Relay-style cursor pagination (first/after + pageInfo). False = single capped request
    # for connections without a cursor.
    paginated: bool = True
    # Extra context surfaced in the schema picker.
    description: Optional[str] = None


SOURCEGRAPH_ENDPOINTS: dict[str, SourcegraphEndpointConfig] = {
    "repositories": SourcegraphEndpointConfig(
        name="repositories",
        query=REPOSITORIES_QUERY,
        data_path="repositories",
        partition_key="createdAt",
    ),
    "users": SourcegraphEndpointConfig(
        name="users",
        query=USERS_QUERY,
        data_path="users",
        description="Requires a site-admin access token",
    ),
    "organizations": SourcegraphEndpointConfig(
        name="organizations",
        query=ORGANIZATIONS_QUERY,
        data_path="organizations",
        paginated=False,
        description="Requires a site-admin access token",
    ),
}

ENDPOINTS = tuple(SOURCEGRAPH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SOURCEGRAPH_ENDPOINTS.items()
}
