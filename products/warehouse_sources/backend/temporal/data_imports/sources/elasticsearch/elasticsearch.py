import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

# Scroll pages cap at 1000 docs to stay well under the pipeline's buffering thresholds.
PAGE_SIZE = 1000
# Scroll contexts are kept alive between page fetches for this long.
SCROLL_KEEPALIVE = "5m"
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5

# Stable prefix for the non-JSON response error. Shared so source.py can match it in
# get_non_retryable_errors without the two strings silently drifting apart.
NON_JSON_RESPONSE_ERROR = "Elasticsearch returned a non-JSON response"

# Elasticsearch numeric types whose _source JSON alternates between whole (40) and fractional
# (40.5) representations across documents. Left alone, that makes a column infer as int64 on one
# scroll page and double on the next, which PyArrow/Delta refuse to merge ("incompatible types:
# int64 vs double"). Coercing these fields to float up front pins the type deterministically.
# Integer types (long/integer/short/byte) are excluded on purpose: they're always whole in JSON,
# and widening a large `long` id to float64 would silently lose precision past 2^53.
_ES_FLOAT_TYPES = frozenset({"float", "double", "half_float", "scaled_float"})


class ElasticsearchRetryableError(Exception):
    pass


@dataclasses.dataclass
class ElasticsearchAuth:
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the cluster URL and reject anything that isn't plain http(s)."""
    host = host.strip()
    if not host:
        raise ValueError("Elasticsearch host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Elasticsearch host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _get_session(auth: ElasticsearchAuth) -> requests.Session:
    secrets = tuple(value for value in (auth.password, auth.api_key) if value)
    session = make_tracked_session(redact_values=secrets, allow_redirects=False)
    if auth.api_key:
        session.headers["Authorization"] = f"ApiKey {auth.api_key}"
    elif auth.username is not None:
        session.auth = (auth.username, auth.password or "")
    return session


def validate_credentials(host: str, auth: ElasticsearchAuth) -> bool:
    """Confirm the cluster is reachable and the credentials are valid via the root info endpoint."""
    try:
        response = _get_session(auth).get(f"{normalize_host(host)}/", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def list_indices(host: str, auth: ElasticsearchAuth) -> list[str]:
    """List non-system indices (system indices start with a dot)."""
    session = _get_session(auth)
    response = session.get(
        f"{normalize_host(host)}/_cat/indices?format=json&h=index",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        # A 2xx body that isn't JSON usually means the URL points at something other than
        # the Elasticsearch HTTP API (e.g. a browser/Kibana URL or a reverse proxy).
        raise ValueError(
            f"{NON_JSON_RESPONSE_ERROR}. Check that the cluster URL points "
            "at the Elasticsearch HTTP API, not a browser or Kibana URL."
        ) from None
    indices = [row.get("index", "") for row in body if isinstance(row, dict)]
    return sorted(index for index in indices if index and not index.startswith("."))


def _collect_float_paths(properties: dict[str, Any], prefix: str, paths: set[str]) -> None:
    """Walk an Elasticsearch mapping's `properties` tree, recording dotted paths of float-typed fields."""
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}{name}"
        if spec.get("type") in _ES_FLOAT_TYPES:
            paths.add(path)
        sub_properties = spec.get("properties")
        if isinstance(sub_properties, dict):
            _collect_float_paths(sub_properties, f"{path}.", paths)


def get_float_field_paths(session: requests.Session, base_url: str, index: str) -> set[str]:
    """Dotted paths of fields the index mapping types as floating point.

    Best-effort: a mapping we can't read (permissions, non-JSON body) yields no paths, so the sync
    behaves as before rather than failing on the mapping lookup alone.
    """
    try:
        response = session.get(f"{base_url}/{quote(index)}/_mapping", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
    except (requests.exceptions.RequestException, requests.exceptions.JSONDecodeError, ValueError):
        return set()

    paths: set[str] = set()
    # Shape: {"<index>": {"mappings": {"properties": {...}}}}. An alias resolves to several indices,
    # so union every block's float paths.
    if isinstance(body, dict):
        for index_block in body.values():
            properties = ((index_block or {}).get("mappings") or {}).get("properties")
            if isinstance(properties, dict):
                _collect_float_paths(properties, "", paths)
    return paths


def _to_float(value: Any) -> Any:
    # bool is an int subclass but never a numeric field value here — leave it untouched.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, list):
        return [_to_float(item) for item in value]
    return value


def _coerce_path(obj: Any, parts: list[str]) -> None:
    key = parts[0]
    if isinstance(obj, list):
        for item in obj:
            _coerce_path(item, parts)
        return
    if not isinstance(obj, dict) or key not in obj:
        return
    if len(parts) == 1:
        obj[key] = _to_float(obj[key])
    else:
        _coerce_path(obj[key], parts[1:])


def coerce_float_fields(doc: dict[str, Any], float_paths: set[str]) -> None:
    """Rewrite whole-number values under float-typed fields to float, in place."""
    for path in float_paths:
        _coerce_path(doc, path.split("."))


def get_rows(
    host: str,
    auth: ElasticsearchAuth,
    index: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(auth)
    base_url = normalize_host(host)
    float_paths = get_float_field_paths(session, base_url, index)

    @retry(
        retry=retry_if_exception_type((ElasticsearchRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def post(url: str, body: dict[str, Any]) -> dict[str, Any]:
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise ElasticsearchRetryableError(
                f"Elasticsearch error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Elasticsearch error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # The scroll API gives a stable snapshot of the index for the duration of
    # the walk; scroll ids expire after SCROLL_KEEPALIVE of inactivity, so the
    # walk restarts from scratch on retry rather than persisting state.
    data = post(
        f"{base_url}/{quote(index)}/_search?scroll={SCROLL_KEEPALIVE}",
        {"size": PAGE_SIZE, "sort": ["_doc"], "query": {"match_all": {}}},
    )
    scroll_id: Optional[str] = data.get("_scroll_id")

    try:
        while True:
            hits = ((data.get("hits") or {}).get("hits")) or []
            items = [{**(hit.get("_source") or {}), "_id": hit["_id"]} for hit in hits]

            if float_paths:
                for item in items:
                    coerce_float_fields(item, float_paths)

            if items:
                yield items

            if len(hits) < PAGE_SIZE or not scroll_id:
                break

            data = post(f"{base_url}/_search/scroll", {"scroll": SCROLL_KEEPALIVE, "scroll_id": scroll_id})
            scroll_id = data.get("_scroll_id", scroll_id)
    finally:
        if scroll_id:
            # Best-effort: free the server-side scroll context early.
            try:
                session.delete(
                    f"{base_url}/_search/scroll",
                    json={"scroll_id": [scroll_id]},
                    timeout=10,
                )
            except Exception:
                pass


def elasticsearch_source(
    host: str,
    auth: ElasticsearchAuth,
    index: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    return SourceResponse(
        name=index,
        items=lambda: get_rows(
            host=host,
            auth=auth,
            index=index,
            logger=logger,
        ),
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
