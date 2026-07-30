import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import AuthConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.zonka_feedback.settings import (
    ZONKA_FEEDBACK_ENDPOINTS,
)

# Vendor API version labels — opaque strings, never parsed or ordered. v2.1 is Zonka's current
# stable API; v1 is the legacy label PostHog first shipped against.
ZONKA_API_VERSION_V1 = "v1"
ZONKA_API_VERSION_V2_1 = "v2.1"

# Zonka Feedback hosts data per region; the account's data center is the subdomain of the API host.
# US=us1, EU=e, IN=in are the documented, verifiable identifiers.
DATA_CENTER_IDS: tuple[str, ...] = ("us1", "e", "in")

# The list endpoints default to 25 items per page and allow overriding the page size. We request a
# larger page to cut round trips; pagination terminates on the first empty page, so the request is
# correct whether or not the server honours the larger size.
PAGE_SIZE = 100
# Zonka Feedback paginates from page 1.
FIRST_PAGE = 1
# Cheap endpoint used to confirm an auth token is genuine. The admin-generated token is account-wide,
# so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/surveys"


@dataclasses.dataclass
class ZonkaFeedbackResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def base_url(data_center: str) -> str:
    # Validate against the fixed allowlist before interpolating: a `data_center` carrying URL
    # delimiters (`/`, `#`, `@`) could otherwise retarget the request at an attacker host and leak
    # the bearer token during validation or sync.
    if data_center not in DATA_CENTER_IDS:
        raise ValueError("Unknown Zonka Feedback data center")
    return f"https://{data_center}.apis.zonkafeedback.com"


def _auth_config(auth_token: str) -> AuthConfig:
    # Framework auth (not a hand-built header) so the token is redacted from any raised error message.
    return {"type": "bearer", "token": auth_token}


def zonka_feedback_source(
    auth_token: str,
    data_center: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZonkaFeedbackResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ZONKA_FEEDBACK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(data_center),
            "headers": {"Accept": "application/json"},
            "auth": _auth_config(auth_token),
            # There is no `has_more` flag and the server may cap the page size below what we request,
            # so short pages are not a reliable stop signal — terminate on the first empty page.
            "paginator": PageNumberPaginator(base_page=FIRST_PAGE, page_param="page"),
            # Pin the credentialed request to the validated Zonka Feedback host and reject any 3xx so
            # a compromised or misconfigured endpoint can't retarget the bearer token at another origin.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"page_size": PAGE_SIZE},
                    # `result` is the documented envelope key for paginated list endpoints; a 200 body
                    # missing it means a malformed response, so fail loud rather than silently
                    # advancing past lost rows.
                    "data_selector": "result",
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (already-yielded pages are persisted); merge dedupes on the primary key.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ZonkaFeedbackResumeConfig(next_page=int(state["page"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(auth_token: str, data_center: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the auth token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    # `redact_values` masks the auth token in any captured sample; `allow_redirects=False` pins the
    # credentialed probe to the validated Zonka Feedback host.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(auth_token,), allow_redirects=False),
        f"{base_url(data_center)}{path}?page=1&page_size=1",
        headers={"Authorization": f"Bearer {auth_token}", "Accept": "application/json"},
    )
    if ok:
        return 200, None
    if status in (401, 403):
        return status, None
    if status is None:
        return 0, "Could not connect to Zonka Feedback"
    return status, f"Zonka Feedback returned HTTP {status}"
