from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.g2.settings import (
    G2_BASE_URL,
    G2_ENDPOINTS,
    PAGE_SIZE,
)


class MissingProductIdError(Exception):
    pass


@frozen
class G2ResumeConfig:
    next_url: str | None = None


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.api+json"}


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Merge a JSON:API resource's `attributes` object into its row root, alongside its `id`.

    `rest_source`'s declarative `data_selector` can pull the `data` array out of the envelope, but
    can't reshape each item, so G2's `{id, type, attributes: {...}}` resources are flattened here.
    """
    row = dict(item.get("attributes") or {})
    row["id"] = item.get("id")
    return row


def _extract_error_detail(response: requests.Response) -> str | None:
    """Pull the human-readable reason out of a G2 JSON:API error body, if there is one."""
    try:
        errors = response.json().get("errors", [])
        titles = [str(error["title"]) for error in errors if isinstance(error, dict) and error.get("title")]
        return "; ".join(titles)[:500] if titles else None
    except Exception:
        return None


def _raise_for_status_with_detail(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_error_detail(response)
        if detail:
            raise requests.HTTPError(f"{exc} ({detail})", response=response) from exc
        raise


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _ensure_g2_url(url: str) -> str:
    """Pin a pagination/resume URL to the G2 API origin before it carries the bearer token.

    `links.next` is response-controlled and resume URLs are replayed from persisted state, so
    refuse anything outside the G2 API origin — the token must never be sent to a host we didn't
    choose.
    """
    if not url.startswith(f"{G2_BASE_URL}/"):
        raise ValueError(f"Refusing to follow non-G2 URL: {url}")
    return url


def _fetch_page(session: requests.Session, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=30)
    if not response.ok:
        _raise_for_status_with_detail(response)
    return response.json()


def validate_credentials(access_token: str, api_version: str) -> tuple[bool, int | None]:
    # `/categories` requires no scope, so a 200 here confirms the token itself is genuine without
    # depending on any per-endpoint permission the account may not have granted yet.
    url = _build_url(f"{G2_BASE_URL}/api/{api_version}/categories", {"page[size]": 1})
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        url,
        headers=_headers(access_token),
    )


def get_rows(
    access_token: str,
    endpoint: str,
    product_id: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[G2ResumeConfig],
) -> Iterator[Any]:
    config = G2_ENDPOINTS[endpoint]
    if config.requires_product_id and not product_id:
        raise MissingProductIdError(f"G2 product ID is required to sync {endpoint}")

    path = config.path.format(product_id=product_id) if config.requires_product_id else config.path
    headers = _headers(access_token)
    # `allow_redirects=False`: defense-in-depth so a redirect can't carry the bearer token off
    # the validated host, on top of the origin check in `_ensure_g2_url`.
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = _ensure_g2_url(resume.next_url)
        logger.debug(f"G2: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(f"{G2_BASE_URL}/api/{api_version}{path}", {"page[size]": PAGE_SIZE})

    while True:
        data = _fetch_page(session, url, headers)
        items = data.get("data", [])
        next_url = data.get("links", {}).get("next")
        next_url = _ensure_g2_url(next_url) if next_url else None

        for item in items:
            batcher.batch(_flatten_item(item))

            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding, and only when another page remains, so a crash re-yields the
                # last batch (merge dedupes on primary key) instead of skipping it.
                if next_url:
                    resumable_source_manager.save_state(G2ResumeConfig(next_url=next_url))

        if not next_url:
            break
        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def g2_source(
    access_token: str,
    endpoint: str,
    product_id: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[G2ResumeConfig],
) -> SourceResponse:
    config = G2_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            product_id=product_id,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # G2's OpenAPI spec documents no `sort` parameter or default order for any list endpoint,
        # so no sync here can claim a verified direction (see settings.py).
        sort_mode=None,
    )
