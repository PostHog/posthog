import re
import base64
from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.settings import (
    PAGE_SIZE,
    PARTITION_KEY,
    PRIMARY_KEY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLINIKO_API_VERSION = "v1"

# The characters after the last "-" in an API key are the shard it must be called against
# (https://docs.api.cliniko.com/guides/sharding) — keys minted before sharding existed carry no
# suffix and default to au1.
_SHARD_SUFFIX_RE = re.compile(r"-([a-zA-Z]{2}\d{1,2})$")
_DEFAULT_SHARD = "au1"

# Cliniko blocks requests without a descriptive User-Agent of the form "APP_NAME (email)".
USER_AGENT = "PostHog Data Warehouse (support@posthog.com)"

# Sentinel lower bound for the `updated_at` filter on the first incremental sync (or full
# refresh), well before Cliniko existed. Using it unconditionally means the filter is always
# present when incremental sync is on, instead of special-casing "no watermark yet".
EPOCH_START = "1970-01-01T00:00:00Z"


@frozen
class ClinikoResumeConfig:
    next_url: str


def shard_from_api_key(api_key: str) -> str:
    match = _SHARD_SUFFIX_RE.search(api_key)
    return match.group(1).lower() if match else _DEFAULT_SHARD


def base_url(api_key: str) -> str:
    return f"https://api.{shard_from_api_key(api_key)}.cliniko.com/{CLINIKO_API_VERSION}"


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _updated_at_filter() -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": "updated_at",
        "initial_value": EPOCH_START,
        "convert": lambda value: f"updated_at:>{_to_iso8601(value)}",
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    return {
        "name": name,
        "table_name": name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": name,
            "path": f"/{name}",
            "params": {
                "per_page": PAGE_SIZE,
                "sort": "updated_at:asc" if should_use_incremental_field else "created_at:asc",
                "q[]": _updated_at_filter() if should_use_incremental_field else None,
            },
        },
        "table_format": "delta",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": base_url(api_key),
        "headers": {"Accept": "application/json", "User-Agent": USER_AGENT},
        # Cliniko API keys are used as the basic-auth username with an empty password.
        "auth": {"type": "http_basic", "username": api_key, "password": ""},
        # Cliniko's `links.next` is a full, ready-to-follow URL, so a JSON-body next-URL
        # paginator (rather than manual page counting) fits this and resumes for free.
        "paginator": JSONResponsePaginator(next_url_path="links.next"),
        # Pin every request to base_url's host and refuse redirects: the Basic auth header
        # carries the Cliniko API key, so a spoofed `links.next` target or a cross-origin 3xx
        # must not carry that credential off-host (SSRF). `allowed_hosts=[]` means "same host
        # as base_url only" and also pins paginator and resume URLs.
        "allowed_hosts": [],
        "allow_redirects": False,
        # `capture=False`: rows carry clinical PII (patient records, treatment notes, invoices)
        # the name-based sample scrubbers aren't built to catch, so keep them out of HTTP
        # diagnostic sample storage entirely, same as the other PII/free-text sources.
        "session": make_tracked_session(redact_values=(api_key,), capture=False),
    }


def cliniko_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClinikoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(ClinikoResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEY,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[PARTITION_KEY],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    res = make_tracked_session(redact_values=(api_key,)).get(
        f"{base_url(api_key)}/patients?per_page=1",
        headers={
            "Authorization": f"Basic {basic_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    return res.status_code == 200
