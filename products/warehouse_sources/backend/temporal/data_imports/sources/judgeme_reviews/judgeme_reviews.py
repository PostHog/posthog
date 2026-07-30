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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    JUDGEME_REVIEWS_ENDPOINTS,
)

# The base URL already includes the `/v1` API version segment; endpoint paths are appended to it.
JUDGEME_BASE_URL = "https://judge.me/api/v1"
# per_page maxes out at 100 per Judge.me's docs.
PAGE_SIZE = 100
# Cheap endpoint used to confirm the token + shop domain pair is genuine. The private token is
# shop-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/reviews/count"

# An invalid token/shop domain pair means the credentials are wrong; a 403 typically means a valid
# but public token that can't read reviews. Keep these in sync with `source.py`'s non-retryable errors.
INVALID_CREDENTIALS_MESSAGE = (
    "Your Judge.me shop domain or API token is invalid. Check both under Settings → Integrations → "
    "Judge.me API in the Judge.me admin, then reconnect."
)
FORBIDDEN_MESSAGE = (
    "Your Judge.me API token does not have access to this data. Make sure you are using the private "
    "token, then reconnect."
)


@dataclasses.dataclass
class JudgeMeReviewsResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _normalize_shop_domain(shop_domain: str) -> str:
    # Users paste the domain straight from their browser; strip any scheme/trailing slash so the
    # value matches the bare `example.myshopify.com` format the API expects.
    domain = shop_domain.strip()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]
    return domain.rstrip("/")


def _non_secret_headers() -> dict[str, str]:
    # The private token is supplied via the framework auth config (X-Api-Token header) so it is
    # redacted from logs and error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def judgeme_reviews_source(
    api_token: str,
    shop_domain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[JudgeMeReviewsResumeConfig],
) -> SourceResponse:
    config = JUDGEME_REVIEWS_ENDPOINTS[endpoint]
    domain = _normalize_shop_domain(shop_domain)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": JUDGEME_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "api_key", "api_key": api_token, "name": "X-Api-Token", "location": "header"},
            # No `has_more` flag and per_page may be capped below what we request, so an empty
            # page is the only reliable end-of-collection signal (base_page=1: pages are 1-indexed).
            "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"shop_domain": domain, "per_page": PAGE_SIZE},
                    "data_selector": config.list_key,
                    # A 200 whose body isn't the expected `{"<resource>": [...]}` envelope (bare array,
                    # missing key, non-list value) is treated as transient and reissued rather than
                    # silently advancing the cursor past lost rows.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page > 1:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # from the next page (merge dedupes the re-pulled page on the primary key).
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(JudgeMeReviewsResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
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


def validate_credentials(api_token: str, shop_domain: str) -> tuple[bool, str | None]:
    """Probe a single cheap endpoint to validate the token + shop domain pair.

    The private token is shop-wide, so one probe validates access to every list endpoint.
    """
    domain = _normalize_shop_domain(shop_domain)
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{JUDGEME_BASE_URL}{DEFAULT_PROBE_PATH}?shop_domain={domain}",
        headers={"X-Api-Token": api_token, **_non_secret_headers()},
    )
    if ok:
        return True, None
    if status == 401:
        return False, INVALID_CREDENTIALS_MESSAGE
    if status == 403:
        return False, FORBIDDEN_MESSAGE
    if status is None:
        return False, "Could not connect to Judge.me to validate your credentials"
    return False, f"Judge.me returned HTTP {status}"
