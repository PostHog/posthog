"""Flexmail transport layer.

Flexmail is an email marketing platform. Auth is HTTP Basic (account ID as username, personal
access token as password). Every resource lives under ``https://api.flexmail.eu``.

Responses follow HAL: collection rows live under ``_embedded.item`` (omitted entirely for an empty
collection, so a missing selector legitimately means zero rows) and every row carries navigation
``_links`` that are noise, not data. List endpoints paginate with ``limit``/``offset`` and carry a
top-level ``total``; the segments, opt-in forms and custom fields collections return their whole
result set in one response.

Two tables are per-contact sub-resources (``/contacts/{id}/sources`` and
``/contacts/{id}/interest-subscriptions``) and are fetched once per contact, with the contact's id
carried onto every row so the table can be joined back to ``contacts``.

Every table is full refresh only — no endpoint exposes a server-side timestamp filter, so there is
no incremental cursor to advance.

Built on the shared ``rest_source`` framework: framework ``http_basic`` auth carries the credentials
(and redacts the token from errors/logs), a built-in ``OffsetPaginator`` reproduces the
``limit``/``offset`` + ``total`` termination with resume, ``build_dependent_resource`` drives the
per-contact fan-out, and a ``data_map`` strips each row's ``_links``.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.settings import (
    FLEXMAIL_ENDPOINTS,
    FlexmailEndpointConfig,
)

FLEXMAIL_BASE_URL = "https://api.flexmail.eu"
# List endpoints accept a `limit` of up to 500; the largest page minimises round trips against the
# 60 requests/minute rate limit.
PAGE_SIZE = 500
# Cheap list endpoint used to confirm the credentials are genuine. Personal access tokens are
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/sources"

# HAL collection rows live here; omitted for an empty collection, so a missing selector is a legit
# zero-row page (not an error — no data_selector_required).
_DATA_SELECTOR = "_embedded.item"


@frozen
class FlexmailResumeConfig:
    # Offset of the next page to fetch. Flexmail paginates with `limit`/`offset` query params, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on `id`. `0` means start from the first page.
    offset: int = 0
    # Fan-out endpoints resume on the shape `build_dependent_resource` checkpoints: which contacts
    # finished and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _strip_hal_navigation(item: dict[str, Any]) -> dict[str, Any]:
    # Per-item `_links` are HAL navigation, not data. `_embedded` on a sub-resource row repeats a
    # row of the parent collection we already sync (an interest subscription embeds its interest),
    # so it is navigation too.
    return {k: v for k, v in item.items() if k not in ("_links", "_embedded")}


def _client_config(account_id: str, personal_access_token: str) -> ClientConfig:
    # HTTP Basic auth is supplied via the framework auth config so the token is redacted from logs and
    # raised error messages; only the non-secret Accept header is set here.
    return {
        "base_url": FLEXMAIL_BASE_URL,
        "auth": {
            "type": "http_basic",
            "username": account_id,
            "password": personal_access_token,
        },
        "headers": {"Accept": "application/json"},
    }


def _paginator(config: FlexmailEndpointConfig) -> BasePaginator:
    if config.paginated:
        # `total` is the row count; the paginator stops once offset >= total (or on a short/empty
        # page), matching the hand-rolled `next_offset >= total` termination.
        return OffsetPaginator(limit=PAGE_SIZE, offset_param="offset", limit_param="limit", total_path="total")
    # Segments, opt-in forms, custom fields and a contact's interest subscriptions return the whole
    # collection in one response.
    return SinglePagePaginator()


def _endpoint_extra(config: FlexmailEndpointConfig) -> Endpoint:
    # Each resource carries its own paginator: a fan-out pairs a paginated parent with a child that
    # may not be paginated at all.
    return {"paginator": _paginator(config), "data_selector": _DATA_SELECTOR}


def _flat_resource(
    *,
    config: FlexmailEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterable[list[dict[str, Any]]]:
    rest_config: RESTAPIConfig = {
        "client": {**client_config, "paginator": _paginator(config)},
        "resources": [
            {
                "name": config.name,
                "endpoint": {"path": config.path, "data_selector": _DATA_SELECTOR},
                "data_map": _strip_hal_navigation,
            }
        ],
    }
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    *,
    config: FlexmailEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_paginator_state: Optional[dict[str, Any]],
) -> Iterable[list[dict[str, Any]]]:
    assert config.fanout is not None
    return build_dependent_resource(
        endpoint_configs=FLEXMAIL_ENDPOINTS,
        child_endpoint=config.name,
        fanout=config.fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra=_endpoint_extra(FLEXMAIL_ENDPOINTS[config.fanout.parent_name]),
        child_endpoint_extra=_endpoint_extra(config),
        # Both paginators send their own page size, so the builder must not add one.
        page_size_param=None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def flexmail_source(
    account_id: str,
    personal_access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FlexmailResumeConfig],
) -> SourceResponse:
    config = FLEXMAIL_ENDPOINTS[endpoint]
    client_config = _client_config(account_id, personal_access_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded so a crash re-fetches the last page (merge dedupes on the
        # primary key) rather than skipping it. SinglePagePaginator never yields resume state, so
        # unpaginated endpoints never checkpoint.
        if not state:
            return
        if config.fanout is not None:
            resumable_source_manager.save_state(FlexmailResumeConfig(fanout_state=state))
            return
        if state.get("offset") is not None:
            resumable_source_manager.save_state(FlexmailResumeConfig(offset=int(state["offset"])))

    def build_resource() -> Iterable[list[dict[str, Any]]]:
        if config.fanout is not None:
            return _fanout_resource(
                config=config,
                client_config=client_config,
                team_id=team_id,
                job_id=job_id,
                resume_hook=save_checkpoint,
                initial_paginator_state=resume.fanout_state if resume else None,
            )
        initial_paginator_state = {"offset": resume.offset} if resume and resume.offset else None
        return _flat_resource(
            config=config,
            client_config=client_config,
            team_id=team_id,
            job_id=job_id,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    def items() -> Iterator[list[dict[str, Any]]]:
        # The fan-out builder has no resource-level `data_map` seam, so sub-resource rows are
        # cleaned here instead.
        for batch in build_resource():
            yield [_strip_hal_navigation(row) for row in batch] if config.fanout is not None else batch

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def validate_credentials(account_id: str, personal_access_token: str) -> tuple[bool, str | None]:
    # Personal access tokens are account-wide, so one probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(personal_access_token,)),
        f"{FLEXMAIL_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        auth=HTTPBasicAuth(account_id, personal_access_token),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flexmail account ID or personal access token"
    if status is not None:
        return False, f"Flexmail returned HTTP {status}"
    return False, "Could not validate Flexmail credentials"
