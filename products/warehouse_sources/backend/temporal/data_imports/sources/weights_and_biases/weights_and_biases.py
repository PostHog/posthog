import json
import time
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.security.url_validation import is_url_allowed

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import WANDB_ENDPOINTS

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


class WeightsAndBiasesRetryableError(Exception):
    pass


class WeightsAndBiasesGraphQLError(Exception):
    pass


class WeightsAndBiasesConfigError(Exception):
    pass


@dataclasses.dataclass
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

_VIEWER_QUERY = "query Viewer { viewer { id username } }"


def _get_session(api_key: str) -> requests.Session:
    # Raw GraphQL authenticates with HTTP basic auth, username "api" — the same credentials
    # `wandb login` writes to .netrc for the official SDK. Redirects are disabled as
    # defense-in-depth: the host is validated up front, and W&B's GraphQL API responds
    # directly, so pinning traffic to the validated host closes a redirect-based SSRF path.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
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
    """Read a streamed response body under both a size cap and a wall-clock transfer deadline.

    The host is customer-controlled, so neither the total size nor the total transfer time can be
    trusted: read in chunks, aborting if the body exceeds MAX_RESPONSE_BYTES or the wall-clock
    deadline passes. The deadline closes the slow-drip hole the per-read inactivity timeout leaves.
    """
    deadline = time.monotonic() + MAX_TRANSFER_SECONDS
    buffer = bytearray()
    while True:
        if time.monotonic() > deadline:
            response.close()
            raise WeightsAndBiasesGraphQLError("Weights & Biases response exceeded the transfer deadline")
        chunk = response.raw.read(RESPONSE_READ_CHUNK_BYTES, decode_content=True)
        if not chunk:
            return bytes(buffer)
        buffer += chunk
        if len(buffer) > MAX_RESPONSE_BYTES:
            response.close()
            raise WeightsAndBiasesGraphQLError("Weights & Biases API returned an oversized response body")


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
) -> Iterator[list[dict[str, Any]]]:
    for edges, end_cursor, has_next in _iter_connection(
        execute, query, variables, connection_path, logger, after=after
    ):
        rows = [{**edge["node"], "projectName": project} for edge in edges if edge.get("node")]
        if rows:
            yield rows
        if has_next:
            resumable_source_manager.save_state(WeightsAndBiasesResumeConfig(project=project, cursor=end_cursor))


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

    @retry(
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

    # Fan-out endpoints iterate every project in the entity. Resolve the saved project-name
    # bookmark to the slice still to process; if the bookmarked project no longer exists,
    # start over from the first project (merge dedupes re-pulled rows on the primary key).
    project_names = list(_iter_all_project_names(execute, entity, logger))
    remaining = project_names
    resume_cursor: str | None = None
    if resume is not None and resume.project is not None and resume.project in project_names:
        remaining = project_names[project_names.index(resume.project) :]
        resume_cursor = resume.cursor
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
        else:  # artifacts
            yield from _get_artifact_rows(execute, entity, project, logger)

        resume_cursor = None  # only the resumed-into project uses the saved cursor
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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
        # Fan-out over projects means rows only ascend within a single project, so the
        # pipeline commits the incremental watermark when a run completes rather than
        # per batch.
        sort_mode="desc",
    )
