import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import (
    TAWK_TO_ENDPOINTS,
    TawkToEndpointConfig,
)

TAWK_TO_BASE_URL = "https://api.tawk.to/v1"
# Community-verified working page size for chat.list; the API's maximum is undocumented.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class TawkToRetryableError(Exception):
    pass


class TawkToApiError(Exception):
    """The API answered 2xx but with `{"ok": false, ...}` in the body."""


@dataclasses.dataclass
class TawkToResumeConfig:
    # Row offset within the property currently being paged through.
    offset: int = 0
    # The property currently being processed — a stable ID bookmark (not a positional index),
    # so properties added/removed between a crash and the retry can't resume us into the wrong
    # property. None for the account-level `properties` endpoint.
    property_id: str | None = None


def _post(
    session: requests.Session,
    api_key: str,
    method: str,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    @retry(
        retry=retry_if_exception_type((TawkToRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def _do_post() -> dict[str, Any]:
        url = f"{TAWK_TO_BASE_URL}/{method}"
        # tawk.to is RPC-over-POST: the API key rides HTTP Basic auth as the username with an
        # empty password, and every parameter goes in the JSON body.
        response = session.post(
            url,
            json=body,
            auth=(api_key, ""),
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # Documented 429 error code is `rate_limited`; reset headers aren't documented, so
        # exponential backoff is the fallback.
        if response.status_code == 429 or response.status_code >= 500:
            raise TawkToRetryableError(f"tawk.to API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"tawk.to API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        data = response.json()
        if data.get("ok") is False:
            raise TawkToApiError(
                f"tawk.to API returned an error for {method}: error={data.get('error')}, message={data.get('message')}"
            )
        return data

    return _do_post()


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. `property.list` with an empty body is the cheapest
    authenticated probe (an invalid key gets `{"ok": false, "error": "auth_error"}` with 401)."""
    try:
        response = make_tracked_session().post(
            f"{TAWK_TO_BASE_URL}/property.list",
            json={},
            auth=(api_key, ""),
            headers={"Accept": "application/json"},
            timeout=10,
        )
        return response.status_code == 200 and response.json().get("ok") is True
    except Exception:
        return False


def _list_property_ids(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[str]:
    data = _post(session, api_key, "property.list", {}, logger)
    return [item["propertyId"] for item in data.get("data") or [] if item.get("propertyId")]


def _paged_property_rows(
    session: requests.Session,
    api_key: str,
    config: TawkToEndpointConfig,
    property_id: str,
    start_offset: int,
    resumable_source_manager: ResumableSourceManager[TawkToResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    offset = start_offset
    prev_items: list[dict[str, Any]] | None = None

    while True:
        data = _post(
            session,
            api_key,
            config.method,
            {"propertyId": property_id, "size": PAGE_SIZE, "offset": offset},
            logger,
        )
        items = data.get("data") or []
        if not items:
            break

        # `offset` pagination is confirmed for chat.list but assumed for other list methods.
        # If the server ignores it and replays the same page, stop instead of looping/duplicating.
        if items == prev_items:
            logger.warning(
                f"tawk.to: {config.method} returned an identical page at offset={offset} for "
                f"property {property_id}; the API may not support offset pagination — stopping early"
            )
            break

        for item in items:
            item.setdefault("propertyId", property_id)
        yield items

        offset += len(items)
        total = data.get("total")
        if len(items) < PAGE_SIZE or (isinstance(total, int) and offset >= total):
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it.
        resumable_source_manager.save_state(TawkToResumeConfig(offset=offset, property_id=property_id))
        prev_items = items


def get_rows(
    api_key: str,
    property_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TawkToResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = TAWK_TO_ENDPOINTS[endpoint]
    # One session reused across every request so urllib3 keeps the connection alive instead of
    # re-handshaking per call.
    session = make_tracked_session()

    if not config.scoped_to_property:
        data = _post(session, api_key, config.method, {}, logger)
        items = data.get("data") or []
        if items:
            yield items
        return

    property_ids = [property_id] if property_id else _list_property_ids(session, api_key, logger)

    # Resolve the saved property-ID bookmark to the slice of properties still to process. If the
    # bookmarked property no longer exists (removed between runs), start over from the first one.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = property_ids
    resume_offset = 0
    if resume is not None and resume.property_id is not None and resume.property_id in property_ids:
        remaining = property_ids[property_ids.index(resume.property_id) :]
        resume_offset = resume.offset
        logger.debug(f"tawk.to: resuming {endpoint} from property {resume.property_id}, offset={resume_offset}")

    for index, pid in enumerate(remaining):
        if config.paginated:
            yield from _paged_property_rows(
                session, api_key, config, pid, resume_offset, resumable_source_manager, logger
            )
        else:
            data = _post(session, api_key, config.method, {"propertyId": pid}, logger)
            items = data.get("data") or []
            for item in items:
                item.setdefault("propertyId", pid)
            if items:
                yield items
        resume_offset = 0  # only the resumed-into property starts at the saved offset

        # Advance the bookmark to the next property so a crash between properties resumes there.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(TawkToResumeConfig(offset=0, property_id=remaining[index + 1]))


def tawk_to_source(
    api_key: str,
    property_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TawkToResumeConfig],
) -> SourceResponse:
    config = TAWK_TO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            property_id=property_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # List order is unverified (the ticket sort enum suggests newest-first defaults). Inert
        # while every endpoint is full-refresh only, but declared desc so a future incremental
        # rollout doesn't inherit a corrupt-watermark default.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
