import re
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.argocd.settings import ARGOCD_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    SourceResponse,
    _is_host_safe,
    make_tracked_session,
    request_deadline,
    stop_at_request_deadline,
)

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5
# A per-application request usually fails for a reason specific to that one application, such
# as a spec the server can't compare or a revision its repository no longer resolves, and the
# application is then skipped. A short budget keeps a large install from waiting out the full
# one once per application.
MAX_CHILD_RETRIES = 2

HOST_NOT_ALLOWED_ERROR = "Argo CD host is not allowed"
HTTPS_REQUIRED_ERROR = "Argo CD host must use HTTPS"
RESPONSE_TOO_LARGE_ERROR = "Argo CD API response exceeded the size limit"
RESPONSE_TIMEOUT_ERROR = "Argo CD API response exceeded the download time limit"

# The host is customer-controlled, so responses are streamed and read under a byte cap —
# an arbitrarily large (or endless) 200 body must fail the sync instead of exhausting
# worker memory. The cap applies to decoded bytes, so a gzip bomb can't slip past it.
MAX_RESPONSE_BYTES = 512 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024

# The per-read timeout only bounds the gap between chunks, so a server can trickle one byte
# just before each read timeout and keep a worker occupied until the activity's 24h timeout.
# A monotonic total-transfer deadline caps how long a single body read may take end to end,
# independent of how the bytes are paced, so this slow-drip path fails the sync instead.
MAX_RESPONSE_SECONDS = 600
# Bytes read from an error body for a diagnostic message. Error bodies are never needed in
# full, so only a short bounded snippet is ever pulled into memory.
_ERROR_SNIPPET_BYTES = 2048

# The applications list is fetched in one response, so batch the yielded rows to keep
# downstream Arrow conversion working on bounded slices.
_ROWS_PER_BATCH = 1000
# Each managed-resource row carries the resource's live and target manifests, so these rows
# are batched smaller to keep a batch's memory footprint comparable to the other endpoints'.
_MANAGED_RESOURCE_ROWS_PER_BATCH = 100

# Per-application endpoints cost one request per application, so bound the walk rather than
# letting a pathological install run unchecked.
MAX_FAN_OUT_APPLICATIONS = 5000
# Argo CD keeps 10 history entries per application by default; this leaves headroom for
# installs that raise revisionHistoryLimit.
MAX_REVISIONS_PER_APPLICATION = 25
# Every per-request limit resets on the next request, so a walk of one request per application
# needs a budget of its own. Without it a host that answers slowly for tens of thousands of
# applications holds an import worker until the activity's 24h timeout. The walk stops at the
# budget and logs what it skipped, the same way it does at the application cap.
MAX_FAN_OUT_SECONDS = 4 * 60 * 60

# Repository objects' credential fields are write-only in the Argo CD API, but drop them
# defensively in case a server version ever echoes one back.
_REPOSITORY_SECRET_FIELDS = (
    "password",
    "bearerToken",
    "sshPrivateKey",
    "tlsClientCertData",
    "tlsClientCertKey",
    "githubAppPrivateKey",
    "gcpServiceAccountKey",
)


class ArgocdRetryableError(Exception):
    pass


class ArgocdHostNotAllowedError(Exception):
    pass


class ArgocdResponseTooLargeError(Exception):
    pass


class ArgocdResponseTimeoutError(Exception):
    pass


def _read_bounded(response: requests.Response, max_bytes: int, max_seconds: float = MAX_RESPONSE_SECONDS) -> bytes:
    """Read a streamed response body under both a byte cap and a total-transfer deadline.

    The deadline covers time spent waiting for each chunk, so a slow-drip body that stays
    under the per-read timeout but never finishes is aborted instead of holding the worker.
    """
    total = 0
    chunks: list[bytes] = []
    deadline = time.monotonic() + max_seconds
    for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise ArgocdResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR} ({max_bytes} bytes)")
        if time.monotonic() > deadline:
            raise ArgocdResponseTimeoutError(f"{RESPONSE_TIMEOUT_ERROR} ({max_seconds:g}s)")
        chunks.append(chunk)
    return b"".join(chunks)


def _error_snippet(response: requests.Response) -> str:
    try:
        chunk = next(response.iter_content(chunk_size=_ERROR_SNIPPET_BYTES), b"")
        return chunk[:_ERROR_SNIPPET_BYTES].decode("utf-8", errors="replace")
    except Exception:
        return ""


def normalize_host(host: str | None) -> str:
    """Turn whatever the user typed into an Argo CD base URL.

    Accepts ``argocd.example.com``, ``https://argocd.example.com/``, or
    ``https://argocd.example.com/api/v1`` and returns ``https://argocd.example.com``.
    A path prefix is preserved (Argo CD can be served under a sub-path via ``--rootpath``).
    """
    host = (host or "").strip()
    if not host:
        return ""
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    host = host.rstrip("/")
    host = re.sub(r"/api/v1$", "", host, flags=re.IGNORECASE)
    return host.rstrip("/")


def _host_only(host: str | None) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _has_ambiguous_authority(host: str | None) -> bool:
    """True if ``urlparse`` and the HTTP client could disagree on the real host.

    A backslash (raw or percent-encoded) or userinfo (``@``) in the authority lets the SSRF
    check validate one host while the request reaches another: ``urlparse`` reads the host
    after the ``@`` as the hostname, but a client that folds ``\\`` into ``/`` treats the part
    before it as the host. A real Argo CD URL contains neither, so refuse both.
    """
    raw = host or ""
    if "\\" in raw or "%5c" in raw.lower():
        return True
    return "@" in urlparse(normalize_host(host)).netloc


def _is_https(host: str | None) -> bool:
    # The API token rides in the Authorization header, so refuse plaintext HTTP to keep an
    # on-path attacker from capturing it.
    return urlparse(normalize_host(host)).scheme == "https"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _build_url(host: str | None, path: str, params: Optional[dict[str, Any]] = None) -> str:
    url = f"{normalize_host(host)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def _list_params(endpoint: str, project: str | None) -> dict[str, Any]:
    if not project:
        return {}
    if endpoint == "applicationsets":
        # Filters on the project of the applications each set generates.
        return {"projects": project}
    if endpoint not in ("applications", "deployment_history"):
        return {}
    # The query param scoping the applications list is `projects` on current servers and
    # `project` on older ones; grpc-gateway ignores whichever it doesn't know, so send both.
    return {"project": project, "projects": project}


def _items(data: Any) -> list[dict[str, Any]]:
    # Kubernetes-style List: an empty collection marshals as `"items": null`, not `[]`.
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    return items if isinstance(items, list) else []


def _normalize_application(app: dict[str, Any]) -> dict[str, Any]:
    metadata = app.get("metadata") or {}
    spec = app.get("spec") or {}
    status = app.get("status") or {}
    # Lift identity, timing, and the two headline statuses to the top level so primary
    # keys, partitioning, and common queries resolve against real columns.
    return {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "uid": metadata.get("uid"),
        "created_at": metadata.get("creationTimestamp"),
        "project": spec.get("project"),
        "sync_status": (status.get("sync") or {}).get("status"),
        "health_status": (status.get("health") or {}).get("status"),
        "metadata": metadata,
        "spec": spec,
        "status": status,
        "operation": app.get("operation"),
    }


def _history_rows(app: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = app.get("metadata") or {}
    spec = app.get("spec") or {}
    status = app.get("status") or {}
    return [
        {
            "application_name": metadata.get("name"),
            "application_namespace": metadata.get("namespace"),
            "application_uid": metadata.get("uid"),
            "project": spec.get("project"),
            "id": entry.get("id"),
            "revision": entry.get("revision"),
            "revisions": entry.get("revisions"),
            "deployed_at": entry.get("deployedAt"),
            "deploy_started_at": entry.get("deployStartedAt"),
            "source": entry.get("source"),
            "sources": entry.get("sources"),
            "initiated_by": entry.get("initiatedBy"),
        }
        for entry in status.get("history") or []
        if isinstance(entry, dict)
    ]


def _normalize_project(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    return {
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "created_at": metadata.get("creationTimestamp"),
        "metadata": metadata,
        "spec": item.get("spec"),
        "status": item.get("status"),
    }


def _normalize_applicationset(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    spec = item.get("spec") or {}
    status = item.get("status") or {}
    template_spec = (spec.get("template") or {}).get("spec") or {}
    return {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "uid": metadata.get("uid"),
        "created_at": metadata.get("creationTimestamp"),
        "project": template_spec.get("project"),
        "health_status": (status.get("health") or {}).get("status"),
        "resources_count": status.get("resourcesCount"),
        "metadata": metadata,
        "spec": spec,
        "status": status,
    }


def _normalize_repository(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in _REPOSITORY_SECRET_FIELDS}


def _normalize_cluster(item: dict[str, Any]) -> dict[str, Any]:
    # `config` holds the cluster connection credentials (bearer token, TLS client key);
    # never persist it into the warehouse.
    return {k: v for k, v in item.items() if k != "config"}


def _application_identity(app: dict[str, Any]) -> dict[str, Any]:
    metadata = app.get("metadata") or {}
    spec = app.get("spec") or {}
    return {
        "application_name": metadata.get("name"),
        "application_namespace": metadata.get("namespace"),
        "application_uid": metadata.get("uid"),
        "project": spec.get("project"),
    }


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") or {}
    involved = event.get("involvedObject") or {}
    return {
        "uid": metadata.get("uid"),
        "created_at": metadata.get("creationTimestamp"),
        "reason": event.get("reason"),
        "message": event.get("message"),
        "type": event.get("type"),
        "action": event.get("action"),
        "count": event.get("count"),
        "first_timestamp": event.get("firstTimestamp"),
        "last_timestamp": event.get("lastTimestamp"),
        "event_time": event.get("eventTime"),
        "involved_object_kind": involved.get("kind"),
        "involved_object_name": involved.get("name"),
        "involved_object_namespace": involved.get("namespace"),
        "involved_object_uid": involved.get("uid"),
        "reporting_component": event.get("reportingComponent"),
        "reporting_instance": event.get("reportingInstance"),
        "source": event.get("source"),
        "series": event.get("series"),
        "metadata": metadata,
    }


def _normalize_managed_resource(item: dict[str, Any]) -> dict[str, Any]:
    return {
        # Key columns must never be null: a core-API resource has no group and a
        # cluster-scoped one has no namespace.
        "group": item.get("group") or "",
        "kind": item.get("kind") or "",
        "namespace": item.get("namespace") or "",
        "name": item.get("name") or "",
        "modified": item.get("modified"),
        "hook": item.get("hook"),
        "resource_version": item.get("resourceVersion"),
        "diff": item.get("diff"),
        "live_state": item.get("liveState"),
        "target_state": item.get("targetState"),
        "normalized_live_state": item.get("normalizedLiveState"),
        "predicted_live_state": item.get("predictedLiveState"),
    }


def _normalize_resource_node(node: dict[str, Any], *, orphaned: bool) -> dict[str, Any]:
    health = node.get("health") or {}
    return {
        "group": node.get("group") or "",
        "kind": node.get("kind") or "",
        "namespace": node.get("namespace") or "",
        "name": node.get("name") or "",
        "uid": node.get("uid"),
        "version": node.get("version"),
        # Orphaned resources live in the application's namespace but are not managed by it.
        "orphaned": orphaned,
        "created_at": node.get("createdAt"),
        "health_status": health.get("status"),
        "health_message": health.get("message"),
        "resource_version": node.get("resourceVersion"),
        "images": node.get("images"),
        "info": node.get("info"),
        "parent_refs": node.get("parentRefs"),
        "networking_info": node.get("networkingInfo"),
    }


def _normalize_revision_metadata(data: dict[str, Any], revision: str, source_index: int) -> dict[str, Any]:
    return {
        "revision": revision,
        "source_index": source_index,
        "author": data.get("author"),
        "date": data.get("date"),
        "message": data.get("message"),
        "tags": data.get("tags"),
        "references": data.get("references"),
        "signature_info": data.get("signatureInfo"),
        "source_integrity_result": data.get("sourceIntegrityResult"),
    }


@dataclass(frozen=True)
class _ChartRequest:
    revision: str
    source_index: int
    history_id: int | None
    repo_url: str
    chart: str


def _normalize_chart_details(data: dict[str, Any], request: _ChartRequest) -> dict[str, Any]:
    return {
        "repo_url": request.repo_url,
        "chart": request.chart,
        "revision": request.revision,
        "source_index": request.source_index,
        "history_id": request.history_id,
        "description": data.get("description"),
        "home": data.get("home"),
        "maintainers": data.get("maintainers"),
    }


def _child_params(app: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Scope a per-application request to the application it was walked from.

    With apps-in-any-namespace the name alone is ambiguous, and the project is what the
    server checks the token's RBAC against.
    """
    metadata = app.get("metadata") or {}
    spec = app.get("spec") or {}
    params: dict[str, Any] = {}
    if metadata.get("namespace"):
        params["appNamespace"] = metadata["namespace"]
    if spec.get("project"):
        params["project"] = spec["project"]
    if extra:
        params.update(extra)
    return params


def _child_url(host: str, path: str, app: dict[str, Any], revision: Optional[str] = None, **params: Any) -> str:
    name = (app.get("metadata") or {}).get("name") or ""
    path = path.replace("{name}", quote(name, safe=""))
    if revision is not None:
        path = path.replace("{revision}", quote(revision, safe=""))
    return _build_url(host, path, _child_params(app, params))


def _revision_requests(app: dict[str, Any]) -> list[tuple[str, int]]:
    """Distinct (revision, source index) pairs to resolve for one application.

    Multi-source applications record one revision per source and the API resolves each by its
    index. Chart revisions are left out: this endpoint resolves git commits through the repo
    server, and a Helm chart version has its own endpoint. History runs oldest first, so it is
    walked backwards to keep the most recent revisions when the cap bites.
    """
    history = (app.get("status") or {}).get("history") or []
    pairs: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        sources = entry.get("sources") or []
        revisions = entry.get("revisions") or []
        if revisions:
            candidates = [
                (rev, index, sources[index] if index < len(sources) else {}) for index, rev in enumerate(revisions)
            ]
        else:
            candidates = [(entry.get("revision"), 0, entry.get("source") or {})]
        for revision, source_index, source in candidates:
            if not revision or (isinstance(source, dict) and source.get("chart")):
                continue
            if (revision, source_index) in seen:
                continue
            seen.add((revision, source_index))
            pairs.append((revision, source_index))
            if len(pairs) >= MAX_REVISIONS_PER_APPLICATION:
                return pairs
    return pairs


def _chart_requests(app: dict[str, Any]) -> list[_ChartRequest]:
    """Distinct Helm chart versions an application deployed, newest first.

    The server resolves a chart revision against the application's current sources unless it
    gets the history id, and a chart or repository can change between deployments, so each
    request names the history entry it came from.
    """
    history = (app.get("status") or {}).get("history") or []
    chart_requests: list[_ChartRequest] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        sources = entry.get("sources") or []
        revisions = entry.get("revisions") or []
        if revisions:
            candidates = [
                (rev, index, sources[index] if index < len(sources) else {}) for index, rev in enumerate(revisions)
            ]
        else:
            candidates = [(entry.get("revision"), 0, entry.get("source") or {})]
        history_id = entry.get("id")
        for revision, source_index, source in candidates:
            if not revision or not isinstance(source, dict) or not source.get("chart"):
                continue
            key = (source.get("repoURL") or "", source["chart"], revision)
            if key in seen:
                continue
            seen.add(key)
            chart_requests.append(
                _ChartRequest(
                    revision=revision,
                    source_index=source_index,
                    history_id=history_id if isinstance(history_id, int) else None,
                    repo_url=key[0],
                    chart=key[1],
                )
            )
            if len(chart_requests) >= MAX_REVISIONS_PER_APPLICATION:
                return chart_requests
    return chart_requests


def _fetch_child(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    parent_label: str,
) -> Any:
    """Fetch a per-parent endpoint, returning ``None`` when the parent is skipped.

    These endpoints fail for one application at a time in ways a retry cannot fix: the
    application was deleted during the walk, its spec does not compare so the server holds no
    cached state, or its revision is not a commit the repo server can resolve. Argo CD reports
    those as a 404 or a 500, so one broken application must not fail the whole table. A project
    or repository fails the same way, for example a repository the repo server can't reach.
    A rejected token or a blocked host still fails the sync.
    """
    try:
        return _fetch(session, url, headers, logger, attempts=MAX_CHILD_RETRIES)
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code in (401, 403):
            raise
        logger.warning(f"Argo CD: skipping {parent_label} for this endpoint: {e}")
        return None
    except (ArgocdRetryableError, requests.ReadTimeout, requests.ConnectionError) as e:
        logger.warning(f"Argo CD: skipping {parent_label} for this endpoint: {e}")
        return None


def _project_event_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    project: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    metadata = project.get("metadata") or {}
    name = metadata.get("name") or ""
    path = ARGOCD_ENDPOINTS["project_events"].path.replace("{name}", quote(name, safe=""))
    data = _fetch_child(session, _build_url(host, path), headers, logger, f"project {name}")
    for item in _items(data):
        yield {"project_name": name, "project_uid": metadata.get("uid"), **_normalize_event(item)}


def _repository_ref_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    repository: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    repo = repository.get("repo") or ""
    path = ARGOCD_ENDPOINTS["repository_refs"].path.replace("{repo}", quote(repo, safe=""))
    # A project-scoped repository is only found when the request names its project.
    params = {"appProject": repository["project"]} if repository.get("project") else None
    data = _fetch_child(session, _build_url(host, path, params), headers, logger, f"repository {repo}")
    if not isinstance(data, dict):
        return
    for ref_type, key in (("branch", "branches"), ("tag", "tags")):
        for ref in data.get(key) or []:
            if isinstance(ref, str) and ref:
                yield {"repo": repo, "repo_project": repository.get("project"), "ref_type": ref_type, "name": ref}


def _child_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    endpoint: str,
    parent: dict[str, Any],
    logger: FilteringBoundLogger,
    deadline: float,
) -> Iterator[dict[str, Any]]:
    if endpoint == "project_events":
        yield from _project_event_rows(session, host, headers, parent, logger)
        return
    if endpoint == "repository_refs":
        yield from _repository_ref_rows(session, host, headers, parent, logger)
        return

    app = parent
    identity = _application_identity(app)
    app_label = f"application {identity['application_namespace']}/{identity['application_name']}"
    path = ARGOCD_ENDPOINTS[endpoint].path

    if endpoint == "chart_details":
        for chart_request in _chart_requests(app):
            if time.monotonic() > deadline:
                return
            extra: dict[str, Any] = {"sourceIndex": chart_request.source_index}
            if chart_request.history_id is not None:
                extra["versionId"] = chart_request.history_id
            url = _child_url(host, path, app, revision=chart_request.revision, **extra)
            data = _fetch_child(session, url, headers, logger, app_label)
            if isinstance(data, dict):
                yield {**identity, **_normalize_chart_details(data, chart_request)}
        return

    if endpoint == "revision_metadata":
        for revision, source_index in _revision_requests(app):
            if time.monotonic() > deadline:
                return
            url = _child_url(host, path, app, revision=revision, sourceIndex=source_index)
            data = _fetch_child(session, url, headers, logger, app_label)
            if isinstance(data, dict):
                yield {**identity, **_normalize_revision_metadata(data, revision, source_index)}
        return

    data = _fetch_child(session, _child_url(host, path, app), headers, logger, app_label)
    if data is None:
        return

    if endpoint == "application_events":
        for item in _items(data):
            yield {**identity, **_normalize_event(item)}
    elif endpoint == "managed_resources":
        for item in _items(data):
            yield {**identity, **_normalize_managed_resource(item)}
    else:
        # The resource tree is not a Kubernetes List: managed and orphaned resources arrive in
        # separate arrays.
        nodes = data.get("nodes") if isinstance(data, dict) else None
        orphaned_nodes = data.get("orphanedNodes") if isinstance(data, dict) else None
        for node in nodes or []:
            yield {**identity, **_normalize_resource_node(node, orphaned=False)}
        for node in orphaned_nodes or []:
            yield {**identity, **_normalize_resource_node(node, orphaned=True)}


def _fan_out_parents(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    endpoint: str,
    logger: FilteringBoundLogger,
    project: str | None,
) -> list[dict[str, Any]]:
    parent = ARGOCD_ENDPOINTS[endpoint].fan_out_parent
    url = _build_url(host, ARGOCD_ENDPOINTS[parent].path, _list_params(parent, project))
    parents = _items(_fetch(session, url, headers, logger))
    if endpoint == "repository_refs":
        # Only git repositories have refs. The same URL can be registered both globally and
        # per project, and its refs are the same, so it is fetched once.
        seen: set[str] = set()
        git_repositories = []
        for repository in parents:
            repo = repository.get("repo")
            if not repo or (repository.get("type") or "git") != "git" or repo in seen:
                continue
            seen.add(repo)
            git_repositories.append(repository)
        parents = git_repositories
    if len(parents) > MAX_FAN_OUT_APPLICATIONS:
        logger.warning(
            f"Argo CD: {endpoint} walks at most {MAX_FAN_OUT_APPLICATIONS} {parent}, "
            f"skipping {len(parents) - MAX_FAN_OUT_APPLICATIONS} of {len(parents)}"
        )
        parents = parents[:MAX_FAN_OUT_APPLICATIONS]
    return parents


def _fan_out_rows(
    session: requests.Session,
    host: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    project: str | None,
) -> Iterator[list[dict[str, Any]]]:
    headers = _get_headers(api_token)
    parents = _fan_out_parents(session, host, headers, endpoint, logger, project)

    rows_per_batch = _MANAGED_RESOURCE_ROWS_PER_BATCH if endpoint == "managed_resources" else _ROWS_PER_BATCH
    deadline = time.monotonic() + MAX_FAN_OUT_SECONDS
    batch: list[dict[str, Any]] = []
    for index, parent in enumerate(parents):
        if time.monotonic() > deadline:
            logger.warning(
                f"Argo CD: {endpoint} reached its {MAX_FAN_OUT_SECONDS}s budget after {index} parents, "
                f"skipping the remaining {len(parents) - index}"
            )
            break
        for row in _child_rows(session, host, headers, endpoint, parent, logger, deadline):
            batch.append(row)
            if len(batch) >= rows_per_batch:
                yield batch
                batch = []
    if batch:
        yield batch


def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    attempts: int = MAX_RETRIES,
) -> Any:
    retrying = Retrying(
        retry=retry_if_exception_type((ArgocdRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(attempts) | stop_at_request_deadline(),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    with request_deadline():
        return retrying(_fetch_once, session, url, headers, logger)


def _fetch_once(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    # Don't follow redirects: the customer-controlled host could 3xx to an internal address,
    # bypassing the host validation done before the request (SSRF). `stream=True` so bodies
    # are only read through `_read_bounded` / `_error_snippet` under a byte cap.
    with session.get(
        url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
    ) as response:
        if response.status_code == 429 or response.status_code >= 500:
            raise ArgocdRetryableError(f"Argo CD API error (retryable): status={response.status_code}, url={url}")

        if response.is_redirect or response.is_permanent_redirect:
            raise ArgocdHostNotAllowedError(
                f"Argo CD API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )

        if not response.ok:
            logger.error(
                f"Argo CD API error: status={response.status_code}, body={_error_snippet(response)}, url={url}"
            )
            response.raise_for_status()

        return json.loads(_read_bounded(response, MAX_RESPONSE_BYTES))


def get_rows(
    host: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    project: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ARGOCD_ENDPOINTS[endpoint]

    if _has_ambiguous_authority(host):
        raise ArgocdHostNotAllowedError(HOST_NOT_ALLOWED_ERROR)

    if not _is_https(host):
        raise ArgocdHostNotAllowedError(HTTPS_REQUIRED_ERROR)

    # Re-check at run time (not just at source-create) in case the host was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        raise ArgocdHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # `capture=False`: raw cluster/repository responses carry credential fields the name-based
    # sample scrubbers can't recognise (camelCase `bearerToken`, `sshPrivateKey`, ...) — they are
    # stripped at row level, but must never reach HTTP sample capture either.
    # `retry=Retry(total=0)`: `_fetch` owns the retry budget via tenacity; leaving the adapter's
    # default retries on would nest under it, so a host that stalls each read could occupy a
    # worker for adapter_attempts × tenacity_attempts × timeout.
    session = make_tracked_session(redact_values=(api_token,), capture=False, retry=Retry(total=0))

    if config.fan_out:
        yield from _fan_out_rows(session, host, api_token, endpoint, logger, project)
        return

    url = _build_url(host, config.path, _list_params(endpoint, project))
    data = _fetch(session, url, _get_headers(api_token), logger)
    items = _items(data)

    rows: list[dict[str, Any]]
    if endpoint == "applications":
        rows = [_normalize_application(item) for item in items]
    elif endpoint == "deployment_history":
        rows = [row for item in items for row in _history_rows(item)]
    elif endpoint == "projects":
        rows = [_normalize_project(item) for item in items]
    elif endpoint == "applicationsets":
        rows = [_normalize_applicationset(item) for item in items]
    elif endpoint == "repositories":
        rows = [_normalize_repository(item) for item in items]
    else:
        rows = [_normalize_cluster(item) for item in items]

    for i in range(0, len(rows), _ROWS_PER_BATCH):
        yield rows[i : i + _ROWS_PER_BATCH]


def validate_credentials(
    host: str,
    api_token: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
    project: str | None = None,
) -> tuple[bool, str | None]:
    """Probe the API to confirm the token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but its
    RBAC may only grant the resources the user intends to sync. A scoped probe treats 403 as
    a hard failure.
    """
    normalized = normalize_host(host)
    hostname = (urlparse(normalized).hostname or "").lower()
    if not normalized or not hostname:
        return False, "Invalid Argo CD host"

    if _has_ambiguous_authority(host):
        return False, "Invalid Argo CD host"

    if urlparse(normalized).scheme != "https":
        return False, HTTPS_REQUIRED_ERROR

    # The host is fully customer-controlled, so block hosts that resolve to private/internal
    # addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    endpoint = schema_name if schema_name in ARGOCD_ENDPOINTS else "applications"
    if ARGOCD_ENDPOINTS[endpoint].fan_out:
        # A per-parent endpoint needs a parent name in its path. It is only reached by walking
        # the parent list and needs the same `get` permission, so probing that list is the
        # scoped check.
        endpoint = ARGOCD_ENDPOINTS[endpoint].fan_out_parent
    params = _list_params(endpoint, project)
    if endpoint in ("applications", "deployment_history"):
        # Filtering by a name that can't exist keeps the probe response tiny; servers that
        # don't support the filter just return the full list, which is still a valid probe.
        params = {**params, "name": "posthog-connectivity-probe"}

    try:
        # `capture=False` for the same reason as in `get_rows`: probe responses can carry
        # credential fields the name-based sample scrubbers can't recognise. `stream=True`
        # because the probe runs inline on the API thread and only ever needs the status —
        # the body is never ingested beyond a short error snippet, so a huge response
        # (e.g. an old server ignoring the name filter) can't buffer into memory.
        # `retry=Retry(total=0)`: the probe runs inline on an API worker, so it takes a single
        # attempt — the adapter's default retries would let a stalling host hold the worker for
        # several timeouts instead of one.
        response = make_tracked_session(redact_values=(api_token,), capture=False, retry=Retry(total=0)).get(
            _build_url(normalized, ARGOCD_ENDPOINTS[endpoint].path, params),
            headers=_get_headers(api_token),
            timeout=30,
            allow_redirects=False,
            stream=True,
        )
    except requests.exceptions.SSLError:
        return (
            False,
            "Could not verify the Argo CD server's TLS certificate. The server must present a publicly trusted certificate.",
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to the Argo CD server: {e}"

    with response:
        if response.is_redirect or response.is_permanent_redirect:
            return False, HOST_NOT_ALLOWED_ERROR

        if response.status_code == 200:
            return True, None

        if response.status_code == 401:
            return False, "Invalid Argo CD API token"

        if response.status_code == 403:
            if schema_name is None:
                # Valid token, missing RBAC for this probe — let source creation through.
                return True, None
            return False, f"Your Argo CD API token lacks the RBAC permissions required to sync '{schema_name}'"

        if response.status_code == 429 or response.status_code >= 500:
            return False, "The Argo CD server is temporarily unavailable. Please try again in a moment."

        snippet = _error_snippet(response)
        try:
            body = json.loads(snippet)
            return False, body.get("message") or body.get("error") or snippet
        except Exception:
            return False, snippet


def argocd_source(
    host: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    project: str | None = None,
) -> SourceResponse:
    config = ARGOCD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_token=api_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            project=project,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
