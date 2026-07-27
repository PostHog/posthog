import dataclasses
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.settings import (
    ENDPOINT_SORT_FIELDS,
    ENDPOINTS,
)

POLAR_BASE_URL = "https://api.polar.sh"
PAGE_SIZE = 100


@dataclasses.dataclass
class PolarResumeConfig:
    next_url: str


class PolarPermissionError(Exception):
    pass


def _get_polar_session() -> requests.Session:
    # Plain session with no retry adapter: errors fail fast so the caller
    # can surface them immediately rather than silently retrying.
    return make_tracked_session(retry=Retry(total=0))


def _build_url(endpoint: str, page: int) -> str:
    params: dict[str, str | int] = {"limit": PAGE_SIZE, "page": page}
    sort_field = ENDPOINT_SORT_FIELDS.get(endpoint)
    if sort_field is not None:
        params["sorting"] = sort_field
    return f"{POLAR_BASE_URL}/v1/{endpoint}/?{urlencode(params)}"


def _page_from_url(url: str) -> int:
    qs = parse_qs(urlparse(url).query)
    page_values = qs.get("page", ["1"])
    try:
        return int(page_values[0])
    except (ValueError, IndexError):
        return 1


def get_rows(
    api_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    url: Optional[str] = _build_url(endpoint, page=1)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config and resume_config.next_url:
        url = resume_config.next_url

    session = _get_polar_session()
    seen_urls: set[str] = set()

    while url:
        if url in seen_urls:
            break
        seen_urls.add(url)

        response = session.request("GET", url, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Yield the whole page list; the pipeline batcher handles chunking into
        # pa.Tables at its own thresholds (5000 rows / 200 MiB) and accepts
        # lists directly without per-row overhead.
        items = data.get("items", [])
        if items:
            yield items

        pagination = data.get("pagination") or {}
        max_page = int(pagination.get("max_page") or 0)
        current_page = _page_from_url(url)

        if current_page < max_page:
            url = _build_url(endpoint, page=current_page + 1)
        else:
            url = None

        if url:
            resumable_source_manager.save_state(PolarResumeConfig(next_url=url))
        else:
            resumable_source_manager.save_state(PolarResumeConfig(next_url=""))


def polar_source(
    api_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
) -> SourceResponse:
    def items():
        yield from get_rows(
            api_key=api_key,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints={},
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None) -> bool:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    session = _get_polar_session()

    # When called per-schema (the incremental_fields action), a 403 should surface
    # immediately so the wizard can show "missing permissions for <endpoint>".
    # When called at source-create (no table_name), the user may legitimately have
    # scopes for only a subset of endpoints, so we accept any single non-403
    # response as proof of a usable token. Per-endpoint scope checks are deferred
    # to the per-schema action / first sync. We do require ≥1 readable endpoint —
    # a token that 403s on every endpoint has no usable scope and would create a
    # source guaranteed to fail on first sync.
    if table_name and table_name in ENDPOINTS:
        is_create_probe = False
        endpoints_to_check: list[str] = [table_name]
    elif table_name:
        # A known per-schema caller (incremental_fields) but an endpoint we don't
        # support — reject explicitly rather than silently degrading to the
        # create-probe path, which would falsely pass if any other endpoint is readable.
        raise ValueError(f"Unknown Polar endpoint: {table_name}")
    else:
        is_create_probe = True
        endpoints_to_check = list(ENDPOINTS)

    forbidden: list[str] = []
    last_failure: Optional[requests.Response] = None
    for endpoint in endpoints_to_check:
        response = session.request(
            "GET",
            f"{POLAR_BASE_URL}/v1/{endpoint}/",
            headers=headers,
            params={"limit": 1},
        )
        if response.status_code == 403:
            if is_create_probe:
                forbidden.append(endpoint)
                continue
            raise PolarPermissionError(f"Missing permissions for {endpoint}")
        if is_create_probe:
            # First non-403 success is proof enough — stop probing so a transient
            # 5xx on a later endpoint can't block source creation.
            if response.ok:
                return True
            # Transient non-403 (e.g. 5xx, 401) during create-probe: don't blow
            # up the whole validation — record it and let later endpoints answer.
            last_failure = response
            continue
        response.raise_for_status()

    if is_create_probe:
        if forbidden and not last_failure:
            raise PolarPermissionError(
                f"token has no readable scope for any supported endpoint ({', '.join(forbidden)})"
            )
        if last_failure is not None:
            # Only transient errors (and possibly some 403s) — no endpoint
            # confirmed the token works. Surface the underlying HTTP error so
            # the user gets actionable feedback rather than a silent success.
            last_failure.raise_for_status()

    return True
