from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

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


# Parent listing for the per-repository tables. Ordered by creation so the cursor stays stable while
# new repositories are added mid-run.
REPOSITORY_IDS_QUERY = """
query RepositoryIds($first: Int!, $after: String) {
  repositories(first: $first, after: $after, orderBy: REPOSITORY_CREATED_AT, descending: false) {
    nodes {
      id
      name
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

# History of each repository's default branch. `after` is the page cursor and `afterDate` the date
# filter on current Sourcegraph; older instances used `after` for the date, so declaring `afterDate`
# makes them fail validation loudly instead of misreading the cursor as a date.
COMMITS_QUERY = """
query RepositoryCommits($id: ID!, $first: Int!, $after: String, $afterDate: String) {
  node(id: $id) {
    ... on Repository {
      defaultBranch {
        target {
          commit {
            ancestors(first: $first, after: $after, afterDate: $afterDate) {
              nodes {
                id
                oid
                subject
                body
                url
                author {
                  date
                  person {
                    name
                    email
                    user {
                      id
                      username
                    }
                  }
                }
                committer {
                  date
                  person {
                    name
                    email
                    user {
                      id
                      username
                    }
                  }
                }
                parents {
                  oid
                }
              }
              pageInfo {
                endCursor
                hasNextPage
              }
            }
          }
        }
      }
    }
  }
}
"""

CONTRIBUTORS_QUERY = """
query RepositoryContributors($id: ID!, $first: Int!, $after: String) {
  node(id: $id) {
    ... on Repository {
      contributors(first: $first, after: $after) {
        nodes {
          count
          person {
            name
            email
            displayName
            user {
              id
              username
            }
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
  }
}
"""

# Newest event first; Sourcegraph only keeps exported events for its retention window (24 hours by
# default), so incremental syncs stop paging once they reach the stored watermark.
EXPORTED_EVENTS_QUERY = """
query ExportedEvents($first: Int!, $after: String) {
  telemetry {
    exportedEvents(first: $first, after: $after) {
      nodes {
        id
        exportedAt
        payload
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
}
"""

CODE_HOSTS_QUERY = """
query CodeHosts($first: Int!, $after: String) {
  codeHosts(first: $first, after: $after) {
    nodes {
      id
      kind
      url
      apiRateLimitQuota
      apiRateLimitIntervalSeconds
      gitRateLimitQuota
      gitRateLimitIntervalSeconds
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""

# `config` is left out on purpose: it holds the code host connection's credentials.
EXTERNAL_SERVICES_QUERY = """
query ExternalServices($first: Int!, $after: String) {
  externalServices(first: $first, after: $after) {
    nodes {
      id
      kind
      displayName
      url
      createdAt
      updatedAt
      repoCount
      lastSyncAt
      nextSyncAt
      lastSyncError
      warning
      unrestricted
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=False)
class SourcegraphEndpointConfig:
    name: str
    query: str
    # Dotted path under `data` to the connection (e.g. "repositories", "telemetry.exportedEvents").
    data_path: str
    # Only set where the endpoint can skip already-synced rows on the server side (a date filter, or
    # a newest-first order the sync stops reading at the watermark). Others are full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # GraphQL variable that takes the incremental watermark as a date filter.
    incremental_variable: Optional[str] = None
    # The connection is newest-first on the incremental field, so an incremental sync stops paging
    # once a page reaches the watermark.
    stops_at_watermark: bool = False
    # Run `query` once per repository (`$id`), walking the repositories connection as the parent.
    per_repository: bool = False
    # Stable, immutable field to partition by. Never updatedAt (it mutates).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = 100
    # Relay-style cursor pagination (first/after + pageInfo). False = single capped request
    # for connections without a cursor.
    paginated: bool = True
    # Extra context surfaced in the schema picker.
    description: Optional[str] = None
    sort_mode: Optional[Literal["asc", "desc"]] = "asc"


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
    "commits": SourcegraphEndpointConfig(
        name="commits",
        query=COMMITS_QUERY,
        data_path="node.defaultBranch.target.commit.ancestors",
        per_repository=True,
        # Git filters `afterDate` on the committer date; the author date never changes, so it partitions.
        incremental_fields=[_datetime_field("committedAt")],
        incremental_variable="afterDate",
        partition_key="authoredAt",
        # Each repository is read newest-first on its own, so the rows are not one ordered series.
        sort_mode=None,
        description="Commit history of each repository's default branch",
    ),
    "contributors": SourcegraphEndpointConfig(
        name="contributors",
        query=CONTRIBUTORS_QUERY,
        data_path="node.contributors",
        per_repository=True,
        # Sourcegraph groups contributions by git author name and email per repository.
        primary_keys=["repositoryId", "name", "email"],
        sort_mode=None,
        description="Commit counts per author for each repository",
    ),
    "exported_events": SourcegraphEndpointConfig(
        name="exported_events",
        query=EXPORTED_EVENTS_QUERY,
        data_path="telemetry.exportedEvents",
        incremental_fields=[_datetime_field("timestamp")],
        stops_at_watermark=True,
        partition_key="timestamp",
        sort_mode=None,
        description=(
            "Requires a site-admin access token. Sourcegraph keeps exported events for 24 hours by default, "
            "so sync this table incrementally at least once a day"
        ),
    ),
    "code_hosts": SourcegraphEndpointConfig(
        name="code_hosts",
        query=CODE_HOSTS_QUERY,
        data_path="codeHosts",
        sort_mode=None,
        description="Requires a site-admin access token",
    ),
    "external_services": SourcegraphEndpointConfig(
        name="external_services",
        query=EXTERNAL_SERVICES_QUERY,
        data_path="externalServices",
        sort_mode=None,
        description="Code host connections. Requires a site-admin access token",
    ),
}

ENDPOINTS = tuple(SOURCEGRAPH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SOURCEGRAPH_ENDPOINTS.items()
}
