import dataclasses
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import MAILERLITE_ENDPOINTS

MAILERLITE_BASE_URL = "https://connect.mailerlite.com/api"

# MailerLite caps list endpoints at 100 rows per page; default is 25.
PAGE_SIZE = 100


@dataclasses.dataclass
class MailerLiteResumeConfig:
    # Absolute next-page URL returned by the API (carries the cursor / page number and limit).
    next_url: str


class MailerLiteNextUrlPaginator(JSONResponsePaginator):
    """Follows the absolute ``links.next`` URL MailerLite returns for both cursor (subscribers) and
    page-number (everything else) pagination — but only while it stays on the canonical MailerLite
    host. A tampered or compromised response pointing ``next`` off-host is ignored (pagination
    stops after the current page) so our authenticated request can't be redirected to an internal
    address and leak the API key carried in the Authorization header. Off-host *resume* URLs are
    rejected up front by the client's ``allowed_hosts`` guard instead.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="links.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and (
            not isinstance(self._next_url, str) or not self._next_url.startswith(MAILERLITE_BASE_URL)
        ):
            self._has_next_page = False
            self._next_url = None


def mailerlite_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = MAILERLITE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILERLITE_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": MailerLiteNextUrlPaginator(),
            # Pin every request — including a seeded resume URL — to the MailerLite host so a
            # tampered pagination/resume link can't exfiltrate the Authorization header (SSRF).
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": {"limit": PAGE_SIZE},
                    # Every list response wraps its rows in {"data": [...], "links": {...}, "meta": {...}};
                    # a missing/empty "data" is a legit zero-row page, not an error.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(MailerLiteResumeConfig(next_url=state["next_url"]))

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
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, path: str = "/subscribers") -> bool:
    """Confirm the API key is genuine with one cheap probe against a list endpoint."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MAILERLITE_BASE_URL}{path}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok
