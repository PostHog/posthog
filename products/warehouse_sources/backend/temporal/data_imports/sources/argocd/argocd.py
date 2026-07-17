import re
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.settings import ARGOCD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe

REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRIES = 5

HOST_NOT_ALLOWED_ERROR = "Argo CD host is not allowed"
HTTPS_REQUIRED_ERROR = "Argo CD host must use HTTPS"

# The applications list is fetched in one response, so batch the yielded rows to keep
# downstream Arrow conversion working on bounded slices.
_ROWS_PER_BATCH = 1000

# Repository objects' credential fields are write-only in the Argo CD API, but drop them
# defensively in case a server version ever echoes one back.
_REPOSITORY_SECRET_FIELDS = (
    "password",
    "bearerToken",
    "sshPrivateKey",
    "tlsClientCertData",
    "tlsClientCertKey",
    "githubAppPrivateKey",
)


class ArgocdRetryableError(Exception):
    pass


class ArgocdHostNotAllowedError(Exception):
    pass


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
    if endpoint not in ("applications", "deployment_history") or not project:
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


def _normalize_repository(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in _REPOSITORY_SECRET_FIELDS}


def _normalize_cluster(item: dict[str, Any]) -> dict[str, Any]:
    # `config` holds the cluster connection credentials (bearer token, TLS client key);
    # never persist it into the warehouse.
    return {k: v for k, v in item.items() if k != "config"}


@retry(
    retry=retry_if_exception_type((ArgocdRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    # Don't follow redirects: the customer-controlled host could 3xx to an internal address,
    # bypassing the host validation done before the request (SSRF).
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

    if response.status_code == 429 or response.status_code >= 500:
        raise ArgocdRetryableError(f"Argo CD API error (retryable): status={response.status_code}, url={url}")

    if response.is_redirect or response.is_permanent_redirect:
        raise ArgocdHostNotAllowedError(
            f"Argo CD API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    if not response.ok:
        logger.error(f"Argo CD API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    host: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    project: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ARGOCD_ENDPOINTS[endpoint]

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
    session = make_tracked_session(redact_values=(api_token,), capture=False)
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

    if urlparse(normalized).scheme != "https":
        return False, HTTPS_REQUIRED_ERROR

    # The host is fully customer-controlled, so block hosts that resolve to private/internal
    # addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    endpoint = schema_name if schema_name in ARGOCD_ENDPOINTS else "applications"
    params = _list_params(endpoint, project)
    if endpoint in ("applications", "deployment_history"):
        # Filtering by a name that can't exist keeps the probe response tiny; servers that
        # don't support the filter just return the full list, which is still a valid probe.
        params = {**params, "name": "posthog-connectivity-probe"}

    try:
        # `capture=False` for the same reason as in `get_rows`: probe responses can carry
        # credential fields the name-based sample scrubbers can't recognise.
        response = make_tracked_session(redact_values=(api_token,), capture=False).get(
            _build_url(normalized, ARGOCD_ENDPOINTS[endpoint].path, params),
            headers=_get_headers(api_token),
            timeout=30,
            allow_redirects=False,
        )
    except requests.exceptions.SSLError:
        return (
            False,
            "Could not verify the Argo CD server's TLS certificate. The server must present a publicly trusted certificate.",
        )
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to the Argo CD server: {e}"

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

    try:
        body = response.json()
        return False, body.get("message") or body.get("error") or response.text
    except Exception:
        return False, response.text


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
