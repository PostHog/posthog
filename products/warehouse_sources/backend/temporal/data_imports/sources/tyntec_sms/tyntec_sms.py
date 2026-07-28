import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.tyntec_sms.settings import (
    LIST_ENDPOINTS,
    MAX_REQUEST_IDS,
    MESSAGE_STATUS,
    MESSAGE_STATUS_PATH,
    PHONE_NUMBERS,
    PHONEBOOK_MAX_SIZE,
    PRIMARY_KEYS,
)

logger = structlog.get_logger(__name__)

BASE_URL = "https://api.tyntec.com"
API_KEY_HEADER = "apikey"

# Syntactically valid request id used only to probe credentials: with a valid key the API
# answers 404 (unknown message) while a missing/invalid key is rejected at the gateway with
# 401/403 — verified against the live API.
_CREDENTIALS_PROBE_REQUEST_ID = "00000000-0000-0000-0000-000000000000"


def parse_request_ids(raw: str | None) -> list[str]:
    """Split the user-provided request-id blob on commas/whitespace, deduped, order preserved.

    Capped at ``MAX_REQUEST_IDS`` (each id is one HTTP request per sync)."""
    if not raw:
        return []
    seen: set[str] = set()
    request_ids: list[str] = []
    for token in re.split(r"[\s,]+", raw):
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            request_ids.append(token)
            if len(request_ids) >= MAX_REQUEST_IDS:
                logger.warning(
                    "tyntec_sms request id list truncated",
                    max_request_ids=MAX_REQUEST_IDS,
                )
                break
    return request_ids


def _message_status_rows(api_key: str, request_ids: list[str]) -> Iterator[dict[str, Any]]:
    # Host-pinned with redirects rejected: `requests` only strips `Authorization` on a
    # cross-origin redirect, so following a 30x would replay the `apikey` header off-origin.
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name=API_KEY_HEADER, location="header"),
        allowed_hosts=[],
        allow_redirects=False,
    )
    # tyntec retains message statuses for ~3 months after a final delivery state; expired or
    # unknown ids answer 404 and are skipped instead of failing the sync. Other 4xx (401/403)
    # still raise via the hook's raise_for_status fallback.
    hooks = create_response_hooks([{"status_code": 404, "action": "ignore"}])
    for request_id in request_ids:
        for page in client.paginate(
            path=MESSAGE_STATUS_PATH.format(request_id=quote(request_id, safe="")),
            hooks=hooks,
        ):
            yield from page


def _list_endpoint_resource(endpoint: str) -> EndpointResource:
    path, data_key = LIST_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    if endpoint == PHONE_NUMBERS:
        params["size"] = PHONEBOOK_MAX_SIZE
    return {
        "name": endpoint,
        "table_name": endpoint.lower(),
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": data_key,
            "path": path,
            "params": params,
        },
        "table_format": "delta",
    }


def tyntec_sms_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    request_ids: str | None = None,
) -> SourceResponse:
    if endpoint == MESSAGE_STATUS:
        parsed_ids = parse_request_ids(request_ids)
        return SourceResponse(
            name=endpoint,
            items=lambda: _message_status_rows(api_key, parsed_ids),
            primary_keys=PRIMARY_KEYS[endpoint],
        )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "api_key",
                "name": API_KEY_HEADER,
                "api_key": api_key,
                "location": "header",
            },
            "paginator": "single_page",
            # See _message_status_rows: reject redirects so the apikey header can't leak off-origin.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [_list_endpoint_resource(endpoint)],
    }

    resource = rest_api_resource(config, team_id, job_id, None)

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
    )


def validate_credentials(api_key: str) -> bool:
    session = make_tracked_session(redact_values=(api_key,))
    res = session.get(
        f"{BASE_URL}{MESSAGE_STATUS_PATH.format(request_id=_CREDENTIALS_PROBE_REQUEST_ID)}",
        headers={API_KEY_HEADER: api_key},
        # Don't follow redirects: the apikey header would be replayed to the redirect target.
        allow_redirects=False,
    )
    # 401 = missing/unknown key, 403 = invalid credentials; any other status (typically a 404
    # problem document for the unknown probe id) means the key was accepted.
    return res.status_code not in (401, 403)
