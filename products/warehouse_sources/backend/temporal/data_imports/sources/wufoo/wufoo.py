import re
import base64
import dataclasses
from typing import Any, Optional

from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import WUFOO_ENDPOINTS

# Wufoo enforces a per-account hostname, so only the subdomain label is user-supplied. Restricting
# it to host-safe characters keeps the request pinned to *.wufoo.com.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")

# Wufoo caps `pageSize` at 100 rows per request.
PAGE_SIZE = 100
VALIDATE_TIMEOUT_SECONDS = 10


@dataclasses.dataclass
class WufooResumeConfig:
    # Row offset (Wufoo `pageStart`) of the next page to fetch. Limit/offset pagination is
    # deterministic, so a crashed full-refresh sync resumes from the offset after the last page
    # yielded; merge dedupes any re-pulled rows on the primary key.
    page_start: int = 0


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.wufoo.com/api/v3"


def _basic_token(api_key: str) -> str:
    # Wufoo uses HTTP Basic auth with the API key as the username and any non-empty string as the
    # password — the password value is ignored by Wufoo but must be present.
    return base64.b64encode(f"{api_key}:footastic".encode("ascii")).decode("ascii")


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Basic {_basic_token(api_key)}", "Accept": "application/json"}


def _redact_values(api_key: str) -> tuple[str, ...]:
    # Mask both the raw key and the derived Basic token so neither leaks into logged URLs/samples.
    return (api_key, _basic_token(api_key))


def wufoo_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WufooResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WUFOO_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(subdomain),
            # Only the non-secret Accept header goes here; the credential rides on framework auth
            # so its value is redacted from logs.
            "headers": {"Accept": "application/json"},
            # Wufoo authenticates with HTTP Basic: the API key is the username and any non-empty
            # string is the (ignored) password.
            "auth": {"type": "http_basic", "username": api_key, "password": "footastic"},
            # Wufoo exposes no top-level total; termination is a short/empty page (OffsetPaginator
            # default). pageStart/pageSize are Wufoo's offset/limit params.
            "paginator": OffsetPaginator(
                limit=PAGE_SIZE,
                offset_param="pageStart",
                limit_param="pageSize",
                total_path=None,
            ),
            # Pin every request to the validated subdomain host and reject redirects so the
            # credential can't be replayed to a cross-host target (SSRF / exfiltration defense).
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "data_selector": config.data_key,
                    # A 200 body without the expected list key means the response shape changed —
                    # fail loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.page_start}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(WufooResumeConfig(page_start=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(api_key: str, subdomain: str) -> Optional[int]:
    """Probe a cheap list endpoint. Returns the HTTP status code, or ``None`` on a connection error."""
    if not SUBDOMAIN_REGEX.match(subdomain):
        return None
    url = f"{base_url(subdomain)}/forms.json?pageSize=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(
            redact_values=_redact_values(api_key),
            allow_redirects=False,
            retry=Retry(total=0),
        ),
        url,
        headers=_headers(api_key),
        timeout=VALIDATE_TIMEOUT_SECONDS,
    )
    return status
