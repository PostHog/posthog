import json
import threading
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    is_url_allowed,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.weights_and_biases.settings import WANDB_ENDPOINTS

WANDB_DEFAULT_HOST = "https://api.wandb.ai"
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# The API key travels as HTTP Basic auth, and the host is customer-controlled, so cap the body
# we read from it. A page of 50 runs carries config/summaryMetrics JSON blobs but stays well
# under this; the cap only exists to stop a hostile or misconfigured host exhausting a shared
# warehouse worker with an unbounded (or slowly streamed) response.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
# Bound pagination against a hostile or misconfigured host that keeps returning
# hasNextPage=true with a fresh cursor forever (matching sibling sources). At PAGE_SIZE=50 this
# is 5M rows per connection — far beyond any real entity — so a legitimate sync never hits it,
# while a runaway server can't loop indefinitely or grow the enumerated project list without end.
MAX_PAGES_PER_CONNECTION = 100_000
# Fan-out endpoints (runs/sweeps/reports/artifacts) enumerate every project name up front to
# drive iteration and resume. That list is the one piece of state that grows with the response,
# so bound it: a customer-controlled host could otherwise page back millions of large project
# names (each page is capped, but the accumulated list is not) and exhaust a shared worker. The
# caps sit far above any real entity's project count/name length, so a legitimate sync never
# trips them.
MAX_FAN_OUT_PROJECTS = 250_000
MAX_RETAINED_PROJECT_NAME_BYTES = 16 * 1024 * 1024
RESPONSE_READ_CHUNK_BYTES = 1024 * 1024
# Wall-clock ceiling for consuming a single response body. The request timeout is a per-read
# inactivity limit, so a host that drips a byte before each timeout could hold a worker for the
# whole import; this bounds total transfer time regardless of drip cadence.
MAX_TRANSFER_SECONDS = 120

# Advertised incremental field (row column, camelCase as the API returns it) -> the ascending
# order key the runs connection accepts. Both filter + order verified against the live API.
RUN_INCREMENTAL_SORT_KEYS: dict[str, str] = {
    "createdAt": "+created_at",
    "heartbeatAt": "+heartbeat_at",
}
_DEFAULT_RUN_INCREMENTAL_FIELD = "createdAt"

# Run-child tables page the runs connection with nested data per run, so they use smaller pages
# than PAGE_SIZE to keep each response bounded.
RUN_ARTIFACTS_RUNS_PAGE_SIZE = 20
RUN_ARTIFACTS_PAGE_SIZE = 50
RUN_HISTORY_RUNS_PAGE_SIZE = 10
# A step window is accepted only when it returns at most this many rows. The query asks for twice
# as many samples, so a window the server had to sample comes back larger than this and is split.
RUN_HISTORY_PAGE_SIZE = 1000
RUN_FILES_RUNS_PAGE_SIZE = 20
RUN_FILES_PAGE_SIZE = 50
RUN_EVENTS_RUNS_PAGE_SIZE = 20
# `events` has no range arguments, only `samples`, so a run with more system metric lines than this is
# sampled down by the server. A sample with many GPUs is a few KB, so this keeps one run's response
# well under MAX_RESPONSE_BYTES.
RUN_EVENTS_MAX_SAMPLES = 5000


class WeightsAndBiasesRetryableError(Exception):
    pass


class WeightsAndBiasesGraphQLError(Exception):
    pass


class WeightsAndBiasesConfigError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class WeightsAndBiasesResumeConfig:
    # Project-name bookmark for the fan-out endpoints (runs, sweeps, reports, artifacts). A
    # stable name (not a positional index) so projects added/removed between a crash and the
    # retry can't resume us into the wrong project. None for the top-level projects endpoint.
    project: str | None = None
    # Relay endCursor within the current connection. None means "start the connection at its
    # first page" — used when the bookmark advances to the next project. Artifacts resume at
    # project granularity only (nested type/collection cursors aren't representable), so a
    # resumed project re-walks its artifacts and merge dedupes on the primary key.
    cursor: str | None = None
    # run_history only: the run within the runs page at `cursor`, and the first step to read.
    run: str | None = None
    step: int | None = None


_PROJECTS_QUERY = """
query Projects($entity: String!, $first: Int!, $after: String) {
  models(entityName: $entity, first: $first, after: $after) {
    edges { node { id name entityName description createdAt updatedAt totalRuns } }
    pageInfo { endCursor hasNextPage }
  }
}
"""

_RUNS_QUERY = """
query Runs($entity: String!, $project: String!, $filters: JSONString, $order: String, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    runs(filters: $filters, order: $order, first: $first, after: $after) {
      edges {
        node {
          id name displayName state notes group jobType tags config summaryMetrics systemMetrics
          host commit sweepName createdAt updatedAt heartbeatAt user { username }
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_SWEEPS_QUERY = """
query Sweeps($entity: String!, $project: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    sweeps(first: $first, after: $after) {
      edges {
        node {
          id name displayName state method config createdAt updatedAt heartbeatAt
          runCount runCountExpected bestLoss user { username }
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_REPORTS_QUERY = """
query Reports($entity: String!, $project: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    allViews(viewType: "runs", first: $first, after: $after) {
      edges {
        node {
          id name displayName description type projectName entityName viewCount
          createdAt updatedAt user { username }
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_ARTIFACT_TYPES_QUERY = """
query ArtifactTypes($entity: String!, $project: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    artifactTypes(first: $first, after: $after) {
      edges { node { name } }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_ARTIFACT_COLLECTIONS_QUERY = """
query ArtifactCollections($entity: String!, $project: String!, $type: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    artifactType(name: $type) {
      artifactCollections(first: $first, after: $after) {
        edges { node { name } }
        pageInfo { endCursor hasNextPage }
      }
    }
  }
}
"""

_ARTIFACTS_QUERY = """
query ArtifactVersions($entity: String!, $project: String!, $type: String!, $collection: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    artifactType(name: $type) {
      artifactCollection(name: $collection) {
        artifacts(first: $first, after: $after) {
          edges {
            version
            node {
              id digest description state size fileCount versionIndex metadata commitHash
              createdAt updatedAt
            }
          }
          pageInfo { endCursor hasNextPage }
        }
      }
    }
  }
}
"""

_PROJECT_ARTIFACT_TYPES_QUERY = """
query ProjectArtifactTypes($entity: String!, $project: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    artifactTypes(first: $first, after: $after) {
      edges { node { id name description createdAt } }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_PROJECT_ARTIFACT_COLLECTIONS_QUERY = """
query ProjectArtifactCollections($entity: String!, $project: String!, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    artifactCollections(first: $first, after: $after) {
      edges {
        node {
          __typename id name description createdAt updatedAt
          defaultArtifactType { name }
          tags { edges { node { name } } }
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

# Never request the members' `apiKey` field: it exists on the type but is a credential.
_MEMBERS_QUERY = """
query EntityMembers($entity: String!) {
  entity(name: $entity) {
    members { id username name email admin pending accountType }
  }
}
"""

_ARTIFACT_REF_FIELDS = "id versionIndex artifactType { name } artifactSequence { name }"

_RUN_ARTIFACTS_RUNS_QUERY = f"""
query RunArtifactLineage(
  $entity: String!, $project: String!, $filters: JSONString, $order: String, $first: Int!, $after: String,
  $artifactsFirst: Int!
) {{
  project(entityName: $entity, name: $project) {{
    runs(filters: $filters, order: $order, first: $first, after: $after) {{
      edges {{
        node {{
          id name createdAt heartbeatAt
          inputArtifacts(first: $artifactsFirst) {{
            edges {{ node {{ {_ARTIFACT_REF_FIELDS} }} }}
            pageInfo {{ endCursor hasNextPage }}
          }}
          outputArtifacts(first: $artifactsFirst) {{
            edges {{ node {{ {_ARTIFACT_REF_FIELDS} }} }}
            pageInfo {{ endCursor hasNextPage }}
          }}
        }}
      }}
      pageInfo {{ endCursor hasNextPage }}
    }}
  }}
}}
"""


def _single_run_artifacts_query(connection: str) -> str:
    return f"""
query RunArtifacts($entity: String!, $project: String!, $run: String!, $first: Int!, $after: String) {{
  project(entityName: $entity, name: $project) {{
    run(name: $run) {{
      {connection}(first: $first, after: $after) {{
        edges {{ node {{ {_ARTIFACT_REF_FIELDS} }} }}
        pageInfo {{ endCursor hasNextPage }}
      }}
    }}
  }}
}}
"""


_RUN_ARTIFACT_CONNECTIONS: dict[str, str] = {"input": "inputArtifacts", "output": "outputArtifacts"}
_SINGLE_RUN_ARTIFACTS_QUERIES: dict[str, str] = {
    connection: _single_run_artifacts_query(connection) for connection in _RUN_ARTIFACT_CONNECTIONS.values()
}

_RUN_HISTORY_RUNS_QUERY = """
query RunHistoryRuns($entity: String!, $project: String!, $filters: JSONString, $order: String, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    runs(filters: $filters, order: $order, first: $first, after: $after) {
      edges { node { id name createdAt heartbeatAt historyLineCount historyKeys } }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_RUN_HISTORY_QUERY = """
query RunHistoryPage($entity: String!, $project: String!, $run: String!, $minStep: Int64!, $maxStep: Int64!, $samples: Int!) {
  project(entityName: $entity, name: $project) {
    run(name: $run) { history(minStep: $minStep, maxStep: $maxStep, samples: $samples) }
  }
}
"""

# photoUrl is left out: it is a signed storage URL that changes on every request.
_ENTITY_QUERY = """
query Entity($entity: String!) {
  entity(name: $entity) {
    id name isTeam entityType isPaid privateOnly defaultAccess readOnly codeSavingEnabled storageBytes createdAt
  }
}
"""

# url and directUrl are left out: they are signed download URLs that expire.
_RUN_FILE_FIELDS = "id name sizeBytes mimetype md5 createdAt updatedAt"

_RUN_FILES_RUNS_QUERY = f"""
query RunFilesRuns(
  $entity: String!, $project: String!, $filters: JSONString, $order: String, $first: Int!, $after: String,
  $filesFirst: Int!
) {{
  project(entityName: $entity, name: $project) {{
    runs(filters: $filters, order: $order, first: $first, after: $after) {{
      edges {{
        node {{
          id name createdAt heartbeatAt
          files(first: $filesFirst) {{
            edges {{ node {{ {_RUN_FILE_FIELDS} }} }}
            pageInfo {{ endCursor hasNextPage }}
          }}
        }}
      }}
      pageInfo {{ endCursor hasNextPage }}
    }}
  }}
}}
"""

_SINGLE_RUN_FILES_QUERY = f"""
query RunFiles($entity: String!, $project: String!, $run: String!, $first: Int!, $after: String) {{
  project(entityName: $entity, name: $project) {{
    run(name: $run) {{
      files(first: $first, after: $after) {{
        edges {{ node {{ {_RUN_FILE_FIELDS} }} }}
        pageInfo {{ endCursor hasNextPage }}
      }}
    }}
  }}
}}
"""

_RUN_EVENTS_RUNS_QUERY = """
query RunEventsRuns($entity: String!, $project: String!, $filters: JSONString, $order: String, $first: Int!, $after: String) {
  project(entityName: $entity, name: $project) {
    runs(filters: $filters, order: $order, first: $first, after: $after) {
      edges { node { id name createdAt heartbeatAt eventsLineCount } }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

_RUN_EVENTS_QUERY = """
query RunEvents($entity: String!, $project: String!, $run: String!, $samples: Int!) {
  project(entityName: $entity, name: $project) {
    run(name: $run) { events(samples: $samples) }
  }
}
"""

_VIEWER_QUERY = "query Viewer { viewer { id username } }"


def _get_session(api_key: str) -> requests.Session:
    # Raw GraphQL authenticates with HTTP basic auth, username "api" — the same credentials
    # `wandb login` writes to .netrc for the official SDK. Redirects are disabled as
    # defense-in-depth: the host is validated up front, and W&B's GraphQL API responds
    # directly, so pinning traffic to the validated host closes a redirect-based SSRF path.
    # Accept-Encoding: identity so a compliant host returns uncompressed bytes; combined with
    # reading the body undecoded (see _read_response_body) the size cap bounds true wire bytes,
    # so a customer-controlled host can't ship a small gzip that expands to gigabytes in memory.
    session = make_tracked_session(
        headers={"Accept-Encoding": "identity"}, redact_values=(api_key,), allow_redirects=False
    )
    session.auth = ("api", api_key)
    return session


def _graphql_url(host: str | None) -> str:
    # Dedicated Cloud / self-managed deployments serve the same GraphQL API on an
    # account-specific base URL (e.g. https://acme.wandb.io).
    base = (host or "").strip().rstrip("/")
    if not base:
        return f"{WANDB_DEFAULT_HOST}/graphql"
    # Tolerate a bare host (users routinely paste "acme.wandb.io"); only prepend https when no
    # scheme is present. An explicit http:// is rejected — the key is sent as HTTP Basic auth,
    # so a plaintext scheme would expose it to anyone observing the network path.
    if "://" not in base:
        base = f"https://{base}"
    if urlsplit(base).scheme != "https":
        raise WeightsAndBiasesConfigError(
            "The Weights & Biases host must use https (for example https://acme.wandb.io)."
        )
    url = f"{base}/graphql"
    # Defense-in-depth SSRF check (the Smokescreen egress proxy is the load-bearing control): a
    # custom host is user-supplied, so reject localhost, cloud-metadata, internal domains and
    # private IPs before any request leaves the worker. Runs at credential validation and again
    # on every sync, since both build the URL here.
    allowed, reason = is_url_allowed(url)
    if not allowed:
        raise WeightsAndBiasesConfigError(f"The Weights & Biases host is not allowed: {reason}")
    return url


def validate_host(host: str | None) -> None:
    """Raise WeightsAndBiasesConfigError if a custom host isn't an https URL."""
    _graphql_url(host)


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor as ISO 8601 UTC with Z suffix for a `$gt` filter."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _read_response_body(response: requests.Response) -> bytes:
    """Read a streamed response body under a size cap and a hard wall-clock deadline.

    The host is customer-controlled, so neither total size nor total transfer time can be trusted.
    The read runs on a worker thread so the deadline can interrupt it mid-read: urllib3's blocking
    read won't return while a hostile host drips bytes below the per-read inactivity timeout, so a
    between-reads time check alone can't bound total transfer time. On timeout we close the response
    (which unblocks the stalled read) and raise; an oversized body aborts the same way.
    """
    buffer = bytearray()
    failure: list[BaseException] = []

    def _drain() -> None:
        try:
            while True:
                # decode_content=False: buffer the raw wire bytes without decompressing, so the
                # cap below applies to what actually crossed the network. Decoding here would let
                # a hostile host's gzip bomb balloon a single chunk past the cap before we check.
                chunk = response.raw.read(RESPONSE_READ_CHUNK_BYTES, decode_content=False)
                if not chunk:
                    return
                buffer.extend(chunk)
                if len(buffer) > MAX_RESPONSE_BYTES:
                    return
        except BaseException as exc:  # re-raised to the caller once the thread joins
            failure.append(exc)

    reader = threading.Thread(target=_drain, name="wandb-response-reader", daemon=True)
    reader.start()
    reader.join(MAX_TRANSFER_SECONDS)

    if reader.is_alive():
        response.close()  # unblock the drip-stalled read so the daemon thread can exit
        raise WeightsAndBiasesGraphQLError("Weights & Biases response exceeded the transfer deadline")
    if failure:
        raise failure[0]
    if len(buffer) > MAX_RESPONSE_BYTES:
        response.close()
        raise WeightsAndBiasesGraphQLError("Weights & Biases API returned an oversized response body")
    return bytes(buffer)


def _execute(
    session: requests.Session,
    url: str,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # stream=True so the body isn't buffered before we read it under a cap below.
    response = session.post(
        url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT_SECONDS, stream=True
    )

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise WeightsAndBiasesRetryableError(f"Weights & Biases API error (retryable): status={response.status_code}")

    # We requested Accept-Encoding: identity and read the body undecoded. A host that compresses
    # anyway is either misbehaving or hostile (a decompression bomb), so reject it rather than
    # decode an untrusted, potentially unbounded body.
    content_encoding = response.headers.get("Content-Encoding")
    if content_encoding and content_encoding.strip().lower() not in ("", "identity"):
        response.close()
        raise WeightsAndBiasesGraphQLError(
            f"Weights & Biases API returned an unexpected Content-Encoding: {content_encoding}"
        )

    raw = _read_response_body(response)

    if not response.ok:
        logger.error(
            f"Weights & Biases API error: status={response.status_code}, body={raw[:2000].decode('utf-8', 'replace')}"
        )
        response.raise_for_status()

    body = json.loads(raw)
    errors = body.get("errors")
    if errors:
        message = "; ".join(str(error.get("message", error)) for error in errors)
        raise WeightsAndBiasesGraphQLError(f"Weights & Biases GraphQL error: {message}")

    return body.get("data") or {}


class _NoopLogger:
    def error(self, *args: Any, **kwargs: Any) -> None:
        return None


def validate_credentials(api_key: str, host: str | None) -> bool:
    """Confirm the API key is genuine with the viewer query.

    The API returns 200 with `viewer: null` for a missing/invalid key rather than a 401, so
    validity is a non-null viewer.
    """
    try:
        session = _get_session(api_key)
        data = _execute(session, _graphql_url(host), _VIEWER_QUERY, {}, _NoopLogger())  # type: ignore[arg-type]
        return bool(data.get("viewer"))
    except Exception:
        return False


def _iter_connection(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    query: str,
    variables: dict[str, Any],
    connection_path: tuple[str, ...],
    logger: FilteringBoundLogger,
    after: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None, bool]]:
    """Yield (edges, end_cursor, has_next) pages of a Relay connection.

    Termination follows pageInfo, not edge count: the API returns empty edges with
    hasNextPage=true for pages whose rows are hidden from the caller (verified live), so
    stopping on an empty page would silently truncate. A non-advancing cursor breaks the
    loop as a guard against looping on the same page forever, and MAX_PAGES_PER_CONNECTION
    caps a host that keeps advancing the cursor indefinitely.
    """
    for _ in range(MAX_PAGES_PER_CONNECTION):
        data = execute(query, {**variables, "after": after})
        connection: Any = data
        for key in connection_path:
            connection = (connection or {}).get(key)
        if connection is None:
            # Parent object deleted (or hidden) between enumeration and this fetch.
            return

        edges = connection.get("edges") or []
        page_info = connection.get("pageInfo") or {}
        end_cursor = page_info.get("endCursor")

        yield edges, end_cursor, bool(page_info.get("hasNextPage"))

        if not page_info.get("hasNextPage") or not end_cursor or end_cursor == after:
            return
        after = end_cursor

    logger.warning(
        f"Weights & Biases: hit the {MAX_PAGES_PER_CONNECTION}-page cap for {connection_path}, stopping pagination"
    )


def _iter_all_project_names(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]], entity: str, logger: FilteringBoundLogger
) -> Iterator[str]:
    for edges, _end_cursor, _has_next in _iter_connection(
        execute, _PROJECTS_QUERY, {"entity": entity, "first": PAGE_SIZE}, ("models",), logger
    ):
        for edge in edges:
            node = edge.get("node")
            if node and node.get("name"):
                yield node["name"]


def _collect_fan_out_project_names(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]], entity: str, logger: FilteringBoundLogger
) -> list[str]:
    """Materialise every project name for a fan-out sync under a hard retained-state cap.

    The host is customer-controlled, so refuse to buffer an unbounded list — abort once the
    retained names exceed either cap rather than let a hostile host grow worker memory without
    end. Both caps are far beyond any real entity, so a legitimate sync never hits them.
    """
    names: list[str] = []
    retained_bytes = 0
    for name in _iter_all_project_names(execute, entity, logger):
        names.append(name)
        retained_bytes += len(name.encode("utf-8"))
        if len(names) > MAX_FAN_OUT_PROJECTS or retained_bytes > MAX_RETAINED_PROJECT_NAME_BYTES:
            raise WeightsAndBiasesGraphQLError(
                "Weights & Biases returned an unreasonably large project list; refusing to buffer it"
            )
    return names


def _get_project_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    after: str | None,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    for edges, end_cursor, has_next in _iter_connection(
        execute, _PROJECTS_QUERY, {"entity": entity, "first": PAGE_SIZE}, ("models",), logger, after=after
    ):
        rows = [edge["node"] for edge in edges if edge.get("node")]
        if rows:
            yield rows
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        if has_next:
            resumable_source_manager.save_state(WeightsAndBiasesResumeConfig(cursor=end_cursor))


def _run_query_variables(
    entity: str,
    project: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    field_name = _DEFAULT_RUN_INCREMENTAL_FIELD
    if should_use_incremental_field and incremental_field in RUN_INCREMENTAL_SORT_KEYS:
        field_name = incremental_field

    filters: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        filters = json.dumps({field_name: {"$gt": _format_timestamp(db_incremental_field_last_value)}})

    return {
        "entity": entity,
        "project": project,
        "filters": filters,
        # Always sort explicitly on a stable monotonic field so page boundaries can't skip or
        # duplicate rows as new runs land mid-sync.
        "order": RUN_INCREMENTAL_SORT_KEYS[field_name],
        "first": PAGE_SIZE,
    }


def _get_fan_out_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    query: str,
    variables: dict[str, Any],
    connection_path: tuple[str, ...],
    project: str,
    after: str | None,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
    transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    for edges, end_cursor, has_next in _iter_connection(
        execute, query, variables, connection_path, logger, after=after
    ):
        rows = [
            {**(transform(edge["node"]) if transform else edge["node"]), "projectName": project}
            for edge in edges
            if edge.get("node")
        ]
        if rows:
            yield rows
        if has_next:
            resumable_source_manager.save_state(WeightsAndBiasesResumeConfig(project=project, cursor=end_cursor))


def _artifact_collection_row(node: dict[str, Any]) -> dict[str, Any]:
    tag_edges = (node.get("tags") or {}).get("edges") or []
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        # ArtifactSequence (a regular collection) or ArtifactPortfolio (a collection of linked versions).
        "collectionType": node.get("__typename"),
        "description": node.get("description"),
        "createdAt": node.get("createdAt"),
        "updatedAt": node.get("updatedAt"),
        "artifactTypeName": (node.get("defaultArtifactType") or {}).get("name"),
        "tags": [tag["node"]["name"] for tag in tag_edges if (tag.get("node") or {}).get("name")],
    }


def _get_member_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]], entity: str
) -> Iterator[list[dict[str, Any]]]:
    data = execute(_MEMBERS_QUERY, {"entity": entity})
    members = (data.get("entity") or {}).get("members") or []
    # Pending invites can have no user id yet; they can't resolve a run's user, so skip them.
    rows = [member for member in members if member and member.get("id")]
    if rows:
        yield rows


def _run_child_query_variables(
    entity: str,
    project: str,
    page_size: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    filters: str | None = None
    order = RUN_INCREMENTAL_SORT_KEYS["createdAt"]
    if should_use_incremental_field:
        order = RUN_INCREMENTAL_SORT_KEYS["heartbeatAt"]
        if db_incremental_field_last_value is not None:
            filters = json.dumps({"heartbeatAt": {"$gt": _format_timestamp(db_incremental_field_last_value)}})

    return {"entity": entity, "project": project, "filters": filters, "order": order, "first": page_size}


def _run_child_base(project: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": run.get("id"),
        "runName": run.get("name"),
        "projectName": project,
        "runCreatedAt": run.get("createdAt"),
        "runHeartbeatAt": run.get("heartbeatAt"),
    }


def _run_artifact_rows(base: dict[str, Any], direction: str, edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for edge in edges:
        node = edge.get("node") or {}
        if not node.get("id"):
            continue
        rows.append(
            {
                **base,
                "direction": direction,
                "artifactId": node["id"],
                "artifactTypeName": (node.get("artifactType") or {}).get("name"),
                "collectionName": (node.get("artifactSequence") or {}).get("name"),
                "versionIndex": node.get("versionIndex"),
            }
        )
    return rows


@dataclasses.dataclass(frozen=True)
class _RunCursor:
    run: dict[str, Any]
    # Bookmark that reads this run again from its start (history adds the step to it).
    resume_here: WeightsAndBiasesResumeConfig
    # Bookmark past this run, staged before its last batch is yielded. None for the last run of
    # the project; get_rows then advances the project bookmark.
    after_run: WeightsAndBiasesResumeConfig | None
    first_step: int


@dataclasses.dataclass(frozen=True)
class _RunsPageEnd:
    # Bookmark for the next runs page, or None after the last page.
    next_page: WeightsAndBiasesResumeConfig | None


def _finish_runs_page(
    page_end: _RunsPageEnd, resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig]
) -> None:
    # Every run of the page is read, so the next page is a safe bookmark. The safe point also covers
    # a page whose runs returned no rows, which would otherwise never hand control back.
    if page_end.next_page is not None:
        resumable_source_manager.save_state(page_end.next_page)
    resumable_source_manager.safe_point()


def _iter_runs(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    query: str,
    variables: dict[str, Any],
    project: str,
    resume: WeightsAndBiasesResumeConfig | None,
    logger: FilteringBoundLogger,
) -> Iterator[_RunCursor | _RunsPageEnd]:
    """Walk a project's runs for the run-child tables, with a run-level bookmark for each run.

    After the runs of each page it yields a _RunsPageEnd, which the consumer passes to
    _finish_runs_page once it has read those runs.
    """
    page_after = resume.cursor if resume else None
    resume_run = resume.run if resume else None
    resume_step = (resume.step or 0) if resume else 0

    for edges, end_cursor, has_next in _iter_connection(
        execute, query, variables, ("project", "runs"), logger, after=page_after
    ):
        runs = [edge["node"] for edge in edges if (edge.get("node") or {}).get("name")]
        names = [run["name"] for run in runs]
        # If the bookmarked run is gone, read the whole page again; merge dedupes on the key.
        start = names.index(resume_run) if resume_run in names else 0
        for index in range(start, len(runs)):
            after_run: WeightsAndBiasesResumeConfig | None = None
            if index + 1 < len(runs):
                after_run = WeightsAndBiasesResumeConfig(project=project, cursor=page_after, run=names[index + 1])
            elif has_next:
                after_run = WeightsAndBiasesResumeConfig(project=project, cursor=end_cursor)
            yield _RunCursor(
                run=runs[index],
                resume_here=WeightsAndBiasesResumeConfig(project=project, cursor=page_after, run=names[index]),
                after_run=after_run,
                first_step=resume_step if index == start and resume_run in names else 0,
            )
        yield _RunsPageEnd(
            next_page=WeightsAndBiasesResumeConfig(project=project, cursor=end_cursor) if has_next else None
        )
        resume_run = None
        resume_step = 0
        page_after = end_cursor


def _run_artifact_batches(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    run: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    base = _run_child_base(project, run)
    for direction, connection_name in _RUN_ARTIFACT_CONNECTIONS.items():
        connection = run.get(connection_name) or {}
        yield _run_artifact_rows(base, direction, connection.get("edges") or [])
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            continue
        for more_edges, _c, _h in _iter_connection(
            execute,
            _SINGLE_RUN_ARTIFACTS_QUERIES[connection_name],
            {"entity": entity, "project": project, "run": run["name"], "first": RUN_ARTIFACTS_PAGE_SIZE},
            ("project", "run", connection_name),
            logger,
            after=page_info["endCursor"],
        ):
            yield _run_artifact_rows(base, direction, more_edges)


def _get_run_child_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    runs_query: str,
    variables: dict[str, Any],
    project: str,
    resume: WeightsAndBiasesResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
    run_batches: Callable[[dict[str, Any]], Iterator[list[dict[str, Any]]]],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a project's runs and yield the batches `run_batches` reads for each run, resumable per run."""
    for cursor in _iter_runs(execute, runs_query, variables, project, resume, logger):
        if isinstance(cursor, _RunsPageEnd):
            _finish_runs_page(cursor, resumable_source_manager)
            continue
        # Hold one batch back, so the bookmark past the run is staged before its last batch.
        held: list[dict[str, Any]] | None = None
        for batch in run_batches(cursor.run):
            if held is not None:
                resumable_source_manager.save_state(cursor.resume_here)
                if held:
                    yield held
                else:
                    resumable_source_manager.safe_point()
            held = batch
        if cursor.after_run is not None:
            resumable_source_manager.save_state(cursor.after_run)
        if held:
            yield held
        else:
            resumable_source_manager.safe_point()


def _get_run_artifact_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    variables: dict[str, Any],
    resume: WeightsAndBiasesResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """One row per (run, direction, artifact version), from the runs connection with nested artifact pages.

    The first page of each run's input and output artifacts rides along in the runs query, so a run
    costs an extra request only when it has more artifacts than fit on that page. Each artifact page
    is yielded on its own, so a run with many artifacts never builds up in memory.
    """
    yield from _get_run_child_rows(
        execute,
        _RUN_ARTIFACTS_RUNS_QUERY,
        {**variables, "artifactsFirst": RUN_ARTIFACTS_PAGE_SIZE},
        project,
        resume,
        resumable_source_manager,
        logger,
        partial(_run_artifact_batches, execute, entity, project, logger=logger),
    )


def _run_file_rows(base: dict[str, Any], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for edge in edges:
        node = edge.get("node") or {}
        if not node.get("name"):
            continue
        rows.append(
            {
                **base,
                "id": node.get("id"),
                "name": node["name"],
                "sizeBytes": node.get("sizeBytes"),
                "mimetype": node.get("mimetype"),
                "md5": node.get("md5"),
                "createdAt": node.get("createdAt"),
                "updatedAt": node.get("updatedAt"),
            }
        )
    return rows


def _run_file_batches(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    run: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    base = _run_child_base(project, run)
    connection = run.get("files") or {}
    yield _run_file_rows(base, connection.get("edges") or [])
    page_info = connection.get("pageInfo") or {}
    if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
        return
    for more_edges, _c, _h in _iter_connection(
        execute,
        _SINGLE_RUN_FILES_QUERY,
        {"entity": entity, "project": project, "run": run["name"], "first": RUN_FILES_PAGE_SIZE},
        ("project", "run", "files"),
        logger,
        after=page_info["endCursor"],
    ):
        yield _run_file_rows(base, more_edges)


def _system_metrics_row(base: dict[str, Any], line: Any) -> dict[str, Any] | None:
    entry = json.loads(line) if isinstance(line, str) else line
    if not isinstance(entry, dict):
        return None
    # A sample has no step, so its timestamp is its key within the run.
    timestamp = _history_timestamp(entry.pop("_timestamp", None))
    if timestamp is None:
        return None
    runtime = entry.pop("_runtime", None)
    entry.pop("_wandb", None)
    return {
        **base,
        "timestamp": timestamp,
        "runtime": float(runtime) if isinstance(runtime, int | float) and not isinstance(runtime, bool) else None,
        "metrics": json.dumps(entry, default=str),
    }


def _run_system_metric_batches(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    run: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    if run.get("eventsLineCount") == 0:
        return
    data = execute(
        _RUN_EVENTS_QUERY,
        {"entity": entity, "project": project, "run": run["name"], "samples": RUN_EVENTS_MAX_SAMPLES},
    )
    run_node = (data.get("project") or {}).get("run")
    if run_node is None:
        return  # run deleted between listing and this fetch
    base = _run_child_base(project, run)
    yield [row for row in (_system_metrics_row(base, line) for line in run_node.get("events") or []) if row]


def _get_entity_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]], entity: str
) -> Iterator[list[dict[str, Any]]]:
    node = execute(_ENTITY_QUERY, {"entity": entity}).get("entity")
    if node and node.get("id"):
        yield [node]


def _last_history_step(history_keys: Any) -> int:
    if isinstance(history_keys, str):
        try:
            history_keys = json.loads(history_keys)
        except ValueError:
            return -1
    if not isinstance(history_keys, dict):
        return -1
    last_step = history_keys.get("lastStep")
    return last_step if isinstance(last_step, int) and not isinstance(last_step, bool) else -1


def _history_timestamp(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _history_row(base: dict[str, Any], line: Any) -> dict[str, Any] | None:
    entry = json.loads(line) if isinstance(line, str) else line
    if not isinstance(entry, dict):
        return None
    step = entry.pop("_step", None)
    if isinstance(step, bool) or not isinstance(step, int):
        return None
    runtime = entry.pop("_runtime", None)
    timestamp = entry.pop("_timestamp", None)
    return {
        **base,
        "step": step,
        "timestamp": _history_timestamp(timestamp),
        "runtime": float(runtime) if isinstance(runtime, int | float) and not isinstance(runtime, bool) else None,
        # Metric names are user-defined and differ per run, so they stay in one JSON column
        # rather than becoming table columns.
        "metrics": json.dumps(entry, default=str),
    }


def _initial_history_window(run: dict[str, Any], first_step: int, last_step: int) -> int:
    # Size the first window to hold about one page at the run's average step density, so a run
    # that logs sparse steps (e.g. a sample count as the step) doesn't cost one request per page
    # of empty step range.
    span = last_step + 1 - first_step
    line_count = run.get("historyLineCount")
    if not isinstance(line_count, int) or isinstance(line_count, bool) or line_count <= 0:
        return RUN_HISTORY_PAGE_SIZE
    return max(RUN_HISTORY_PAGE_SIZE, min(span, RUN_HISTORY_PAGE_SIZE * span // line_count))


def _get_single_run_history_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    cursor: _RunCursor,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Read one run's history in step windows [step, step + window).

    `history(samples:)` samples down a window that holds more rows than `samples`. Each window asks
    for twice RUN_HISTORY_PAGE_SIZE samples and is accepted only when it returns at most
    RUN_HISTORY_PAGE_SIZE rows, which proves the server did not sample it. A larger result halves the
    window and reads it again. A window no wider than RUN_HISTORY_PAGE_SIZE steps can't be sampled,
    because steps are unique.
    """
    run = cursor.run
    last_step = _last_history_step(run.get("historyKeys"))
    base = _run_child_base(project, run)
    step = cursor.first_step
    window = _initial_history_window(run, step, last_step)

    for _ in range(MAX_PAGES_PER_CONNECTION):
        if step > last_step:
            return
        data = execute(
            _RUN_HISTORY_QUERY,
            {
                "entity": entity,
                "project": project,
                "run": run["name"],
                "minStep": step,
                "maxStep": step + window,
                "samples": RUN_HISTORY_PAGE_SIZE * 2,
            },
        )
        run_node = (data.get("project") or {}).get("run")
        if run_node is None:
            return  # run deleted between listing and this fetch
        lines = run_node.get("history") or []

        if len(lines) > RUN_HISTORY_PAGE_SIZE and window > RUN_HISTORY_PAGE_SIZE:
            window = max(RUN_HISTORY_PAGE_SIZE, window // 2)
            resumable_source_manager.safe_point()
            continue

        rows = [row for row in (_history_row(base, line) for line in lines) if row is not None]
        step += window
        if len(lines) < RUN_HISTORY_PAGE_SIZE // 2:
            window *= 2

        if step <= last_step:
            resumable_source_manager.save_state(dataclasses.replace(cursor.resume_here, step=step))
        elif cursor.after_run is not None:
            resumable_source_manager.save_state(cursor.after_run)
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

    logger.warning(
        f"Weights & Biases: hit the {MAX_PAGES_PER_CONNECTION}-page cap reading history for run {run['name']}"
    )


def _get_run_history_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    variables: dict[str, Any],
    resume: WeightsAndBiasesResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    for cursor in _iter_runs(execute, _RUN_HISTORY_RUNS_QUERY, variables, project, resume, logger):
        if isinstance(cursor, _RunsPageEnd):
            _finish_runs_page(cursor, resumable_source_manager)
            continue
        yield from _get_single_run_history_rows(execute, entity, project, cursor, resumable_source_manager, logger)


def _get_artifact_rows(
    execute: Callable[[str, dict[str, Any]], dict[str, Any]],
    entity: str,
    project: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk project -> artifact types -> collections -> versions, one row per artifact version."""
    base = {"entity": entity, "project": project, "first": PAGE_SIZE}

    for type_edges, _c, _h in _iter_connection(
        execute, _ARTIFACT_TYPES_QUERY, base, ("project", "artifactTypes"), logger
    ):
        for type_edge in type_edges:
            type_name = (type_edge.get("node") or {}).get("name")
            if not type_name:
                continue

            for collection_edges, _c2, _h2 in _iter_connection(
                execute,
                _ARTIFACT_COLLECTIONS_QUERY,
                {**base, "type": type_name},
                ("project", "artifactType", "artifactCollections"),
                logger,
            ):
                for collection_edge in collection_edges:
                    collection_name = (collection_edge.get("node") or {}).get("name")
                    if not collection_name:
                        continue

                    for artifact_edges, _c3, _h3 in _iter_connection(
                        execute,
                        _ARTIFACTS_QUERY,
                        {**base, "type": type_name, "collection": collection_name},
                        ("project", "artifactType", "artifactCollection", "artifacts"),
                        logger,
                    ):
                        rows = [
                            {
                                **edge["node"],
                                "version": edge.get("version"),
                                "projectName": project,
                                "artifactTypeName": type_name,
                                "collectionName": collection_name,
                            }
                            for edge in artifact_edges
                            if edge.get("node")
                        ]
                        if rows:
                            yield rows


def get_rows(
    api_key: str,
    host: str | None,
    entity: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in WANDB_ENDPOINTS:
        raise ValueError(f"Unknown Weights & Biases endpoint: {endpoint}")

    session = _get_session(api_key)
    url = _graphql_url(host)

    @retry_with_deadline(
        retry=retry_if_exception_type((WeightsAndBiasesRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        # Rate limits are 50-200 req/min per key depending on plan, so back off generously.
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def execute(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return _execute(session, url, query, variables, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint == "projects":
        after = resume.cursor if resume else None
        yield from _get_project_rows(execute, entity, after, resumable_source_manager, logger)
        return

    if endpoint == "members":
        yield from _get_member_rows(execute, entity)
        return

    if endpoint == "entities":
        yield from _get_entity_rows(execute, entity)
        return

    # Fan-out endpoints iterate every project in the entity. Resolve the saved project-name
    # bookmark to the slice still to process; if the bookmarked project no longer exists,
    # start over from the first project (merge dedupes re-pulled rows on the primary key).
    project_names = _collect_fan_out_project_names(execute, entity, logger)
    remaining = project_names
    resume_cursor: str | None = None
    project_resume: WeightsAndBiasesResumeConfig | None = None
    if resume is not None and resume.project is not None and resume.project in project_names:
        remaining = project_names[project_names.index(resume.project) :]
        resume_cursor = resume.cursor
        project_resume = resume
        logger.debug(f"Weights & Biases: resuming {endpoint} from project={resume.project}")

    for index, project in enumerate(remaining):
        if endpoint == "runs":
            variables = _run_query_variables(
                entity, project, should_use_incremental_field, db_incremental_field_last_value, incremental_field
            )
            yield from _get_fan_out_rows(
                execute,
                _RUNS_QUERY,
                variables,
                ("project", "runs"),
                project,
                resume_cursor,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "sweeps":
            yield from _get_fan_out_rows(
                execute,
                _SWEEPS_QUERY,
                {"entity": entity, "project": project, "first": PAGE_SIZE},
                ("project", "sweeps"),
                project,
                resume_cursor,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "reports":
            yield from _get_fan_out_rows(
                execute,
                _REPORTS_QUERY,
                {"entity": entity, "project": project, "first": PAGE_SIZE},
                ("project", "allViews"),
                project,
                resume_cursor,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "artifact_types":
            yield from _get_fan_out_rows(
                execute,
                _PROJECT_ARTIFACT_TYPES_QUERY,
                {"entity": entity, "project": project, "first": PAGE_SIZE},
                ("project", "artifactTypes"),
                project,
                resume_cursor,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "artifact_collections":
            yield from _get_fan_out_rows(
                execute,
                _PROJECT_ARTIFACT_COLLECTIONS_QUERY,
                {"entity": entity, "project": project, "first": PAGE_SIZE},
                ("project", "artifactCollections"),
                project,
                resume_cursor,
                resumable_source_manager,
                logger,
                transform=_artifact_collection_row,
            )
        elif endpoint == "run_artifacts":
            yield from _get_run_artifact_rows(
                execute,
                entity,
                project,
                _run_child_query_variables(
                    entity,
                    project,
                    RUN_ARTIFACTS_RUNS_PAGE_SIZE,
                    should_use_incremental_field,
                    db_incremental_field_last_value,
                ),
                project_resume,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "run_history":
            yield from _get_run_history_rows(
                execute,
                entity,
                project,
                _run_child_query_variables(
                    entity,
                    project,
                    RUN_HISTORY_RUNS_PAGE_SIZE,
                    should_use_incremental_field,
                    db_incremental_field_last_value,
                ),
                project_resume,
                resumable_source_manager,
                logger,
            )
        elif endpoint == "run_files":
            yield from _get_run_child_rows(
                execute,
                _RUN_FILES_RUNS_QUERY,
                {
                    **_run_child_query_variables(
                        entity,
                        project,
                        RUN_FILES_RUNS_PAGE_SIZE,
                        should_use_incremental_field,
                        db_incremental_field_last_value,
                    ),
                    "filesFirst": RUN_FILES_PAGE_SIZE,
                },
                project,
                project_resume,
                resumable_source_manager,
                logger,
                partial(_run_file_batches, execute, entity, project, logger=logger),
            )
        elif endpoint == "run_system_metrics":
            yield from _get_run_child_rows(
                execute,
                _RUN_EVENTS_RUNS_QUERY,
                _run_child_query_variables(
                    entity,
                    project,
                    RUN_EVENTS_RUNS_PAGE_SIZE,
                    should_use_incremental_field,
                    db_incremental_field_last_value,
                ),
                project,
                project_resume,
                resumable_source_manager,
                logger,
                partial(_run_system_metric_batches, execute, entity, project),
            )
        else:  # artifacts
            yield from _get_artifact_rows(execute, entity, project, logger)

        resume_cursor = None  # only the resumed-into project uses the saved cursor
        project_resume = None
        # Advance the bookmark so a crash between projects resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(WeightsAndBiasesResumeConfig(project=remaining[index + 1]))


def weights_and_biases_source(
    api_key: str,
    host: str | None,
    entity: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WeightsAndBiasesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = WANDB_ENDPOINTS[endpoint]
    partition_kwargs: dict[str, Any] = {}
    if endpoint_config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [endpoint_config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            host=host,
            entity=entity,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=list(endpoint_config.primary_keys),
        **partition_kwargs,
        # Fan-out over projects means rows only ascend within a single project, so the
        # pipeline commits the incremental watermark when a run completes rather than
        # per batch.
        sort_mode="desc",
    )
