import re
import json
import time
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.settings import (
    CHATWOOT_ENDPOINTS,
    DEFAULT_HOST,
    MESSAGE_TYPE_TO_INT,
    MESSAGES_PAGE_SIZE,
    ChatwootEndpointConfig,
    all_webhook_events,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Safety valves against a misbehaving (customer-controlled) server that keeps returning rows:
# page-number list endpoints and the per-conversation message walk are otherwise unbounded.
MAX_LIST_PAGES = 100_000
MAX_MESSAGE_PAGES_PER_CONVERSATION = 10_000
# The message walk fans out over every conversation, so the per-conversation cap alone still lets a
# hostile server multiply requests without bound (conversations × pages). This aggregate ceiling
# bounds the total message pages one sync fetches regardless of how many conversations it enumerates.
MAX_MESSAGE_PAGES_PER_SYNC = 1_000_000

# The host is customer-controlled (self-hosted Chatwoot), so a malicious or misconfigured server
# could stream an unbounded body and exhaust a shared worker (requests buffers the whole body into
# memory by default, and the read timeout only guards idle gaps, not a steady large transfer).
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
# requests' timeout only bounds each individual socket read, so a host that dribbles the body
# slowly could hold the connection open far longer than any read timeout while staying under
# MAX_RESPONSE_BYTES. This caps total transfer time per page.
MAX_DOWNLOAD_SECONDS = 300

HOST_NOT_ALLOWED_ERROR = "Chatwoot host is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Chatwoot host must use HTTPS"
RESPONSE_TOO_LARGE_ERROR = "Chatwoot response body was too large"
RESPONSE_TOO_SLOW_ERROR = "Chatwoot response download was too slow"
INVALID_ACCOUNT_ID_ERROR = "Chatwoot account ID must be a number"


class ChatwootRetryableError(Exception):
    pass


class ChatwootHostNotAllowedError(Exception):
    pass


class ChatwootResponseTooLargeError(Exception):
    pass


class ChatwootResponseTooSlowError(Exception):
    pass


@dataclasses.dataclass
class ChatwootResumeConfig:
    # Next page to fetch for page-number endpoints. Stored as a bare page number (not a URL) so
    # stale state can never replay against a different host after the source's host is edited.
    page: int | None = None
    # Messages fan-out bookmark: the conversation (display id) currently being walked, and the
    # last message id already yielded within it (the next request sends `after=<message_id>`).
    conversation_id: int | None = None
    after: int | None = None


def normalize_host(host: str | None) -> str:
    """Turn whatever the user typed into a bare Chatwoot base URL.

    Accepts ``chatwoot.example.com``, ``https://chatwoot.example.com/``, or a URL with a
    trailing ``/api/v1`` and returns ``https://chatwoot.example.com``. Defaults to https when no
    scheme is given, and to Chatwoot Cloud when empty.
    """
    host = (host or "").strip()
    if not host:
        return DEFAULT_HOST
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    host = host.rstrip("/")
    host = re.sub(r"/api(/v[12])?$", "", host, flags=re.IGNORECASE)
    return host.rstrip("/")


def _host_only(host: str | None) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _is_https(host: str | None) -> bool:
    # The access token rides in the api_access_token header, so refuse plaintext HTTP to keep an
    # on-path attacker from capturing it.
    return urlparse(normalize_host(host)).scheme == "https"


def _normalize_account_id(account_id: str | int | None) -> str:
    """Chatwoot account ids are numeric; anything else would be path injection into the URL."""
    account_id_str = str(account_id or "").strip()
    if not account_id_str.isdigit():
        raise ValueError(INVALID_ACCOUNT_ID_ERROR)
    return account_id_str


def _account_base_url(host: str | None, account_id: str | int | None) -> str:
    return f"{normalize_host(host)}/api/v1/accounts/{_normalize_account_id(account_id)}"


def _headers(api_access_token: str) -> dict[str, str]:
    return {"api_access_token": api_access_token, "Accept": "application/json"}


def _ensure_host_allowed(host: str | None, team_id: int) -> None:
    """Run-time host checks — not just at source-create — in case the host was edited or now
    resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud."""
    if not _is_https(host):
        raise ChatwootHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        raise ChatwootHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: {host_err}" if host_err else HOST_NOT_ALLOWED_ERROR
        )


def _make_session(api_access_token: str) -> requests.Session:
    # allow_redirects=False: a customer-controlled host could 3xx at an internal address (SSRF).
    return make_tracked_session(
        headers=_headers(api_access_token), redact_values=(api_access_token,), allow_redirects=False
    )


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream the body into memory, aborting past MAX_RESPONSE_BYTES or MAX_DOWNLOAD_SECONDS.

    Both are non-retryable: re-fetching the same page yields the same oversized/slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise ChatwootResponseTooSlowError(
                    f"{RESPONSE_TOO_SLOW_ERROR}: exceeded {MAX_DOWNLOAD_SECONDS}s download budget"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ChatwootResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@retry(
    retry=retry_if_exception_type((ChatwootRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    # stream=True so the body isn't buffered until we cap it — see _read_capped_body.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True)

    # Chatwoot rate-limits at 3000 req/min per IP (rack-attack default) and returns a plain 429.
    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise ChatwootRetryableError(f"Chatwoot API error (retryable): status={response.status_code}, url={url}")

    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        raise ChatwootHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: Chatwoot returned an unexpected redirect "
            f"(status={response.status_code}); refusing to follow it"
        )

    body = _read_capped_body(response)

    if not response.ok:
        logger.error(
            f"Chatwoot API error: status={response.status_code}, body={body.decode(errors='replace')[:500]}, url={url}"
        )
        response.raise_for_status()

    try:
        return json.loads(body or b"null")
    except ValueError:
        raise ChatwootRetryableError(f"Chatwoot returned a non-JSON payload for {url}")


def _extract_items(data: Any, data_path: tuple[str, ...], url: str) -> list[dict[str, Any]]:
    for key in data_path:
        if not isinstance(data, dict):
            raise ChatwootRetryableError(f"Chatwoot returned an unexpected payload shape for {url}")
        data = data.get(key)
    if data is None:
        return []
    if not isinstance(data, list):
        raise ChatwootRetryableError(f"Chatwoot returned an unexpected payload shape for {url}")
    return data


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def validate_credentials(
    host: str | None, account_id: str | int | None, api_access_token: str, team_id: int
) -> tuple[bool, str | None]:
    """Probe the agents list — the cheapest account-scoped read any user token can perform."""
    if not api_access_token:
        return False, "Missing Chatwoot API access token"

    try:
        base_url = _account_base_url(host, account_id)
    except ValueError:
        return False, INVALID_ACCOUNT_ID_ERROR

    if not _is_https(host):
        return False, HTTP_NOT_ALLOWED_ERROR
    host_ok, host_err = _is_host_safe(_host_only(host), team_id)
    if not host_ok:
        return False, host_err or HOST_NOT_ALLOWED_ERROR

    session = _make_session(api_access_token)
    try:
        # stream=True so a customer-controlled host can't force us to buffer an unbounded probe
        # body: we only inspect the status line here.
        response = session.get(f"{base_url}/agents", timeout=15, allow_redirects=False, stream=True)
    except Exception as e:
        return False, f"Could not connect to Chatwoot: {e}"

    try:
        if response.is_redirect or response.is_permanent_redirect:
            return False, (
                "The Chatwoot instance URL returned an unexpected redirect. Enter just your instance URL "
                "(for example https://app.chatwoot.com or https://chatwoot.example.com) and make sure it "
                "points directly at Chatwoot rather than a login or proxy page."
            )
        if response.status_code == 401:
            return False, (
                "Chatwoot rejected the credentials. Check the API access token is correct and that the "
                "token's user is a member of the configured account."
            )
        if response.status_code == 404:
            return False, "Chatwoot account not found. Check the account ID and instance URL."
        if not response.ok:
            return False, f"Chatwoot returned HTTP {response.status_code}"
        return True, None
    finally:
        response.close()


def _iter_conversation_ids(session: requests.Session, base_url: str, logger: FilteringBoundLogger) -> Iterator[int]:
    """Page through the conversations list (ascending creation order) yielding display ids."""
    page = 1
    while page <= MAX_LIST_PAGES:
        url = _build_url(base_url, "/conversations", {"status": "all", "sort_by": "created_at_asc", "page": page})
        items = _extract_items(_fetch_json(session, url, logger), ("data", "payload"), url)
        if not items:
            return
        for item in items:
            conversation_id = item.get("id")
            if conversation_id is not None:
                yield conversation_id
        page += 1
    logger.warning(f"Chatwoot: conversations enumeration hit the {MAX_LIST_PAGES}-page cap; stopping")


def _get_message_rows(
    session: requests.Session,
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChatwootResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every conversation, walking each one's messages with the id-based `after` cursor.

    `after=0` returns the oldest 100 messages ascending; we advance `after` to the max id seen.
    Pages are ordered by created_at but filtered by id — within a conversation the two orders
    coincide (both are insertion order), which Chatwoot's own clients rely on too.
    """
    conversation_ids = list(_iter_conversation_ids(session, base_url, logger))

    # Resolve the saved conversation bookmark to the slice still to process. If the bookmarked
    # conversation no longer exists, start over from the first one — merge dedupes re-pulled rows
    # on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = conversation_ids
    resume_after: int | None = None
    if resume is not None and resume.conversation_id is not None and resume.conversation_id in conversation_ids:
        remaining = conversation_ids[conversation_ids.index(resume.conversation_id) :]
        resume_after = resume.after
        logger.debug(f"Chatwoot: resuming messages from conversation_id={resume.conversation_id}, after={resume_after}")

    pages_this_sync = 0
    for index, conversation_id in enumerate(remaining):
        after = resume_after if resume_after is not None else 0
        resume_after = None  # only the resumed-into conversation uses the saved cursor

        try:
            pages = 0
            while pages < MAX_MESSAGE_PAGES_PER_CONVERSATION:
                if pages_this_sync >= MAX_MESSAGE_PAGES_PER_SYNC:
                    logger.warning(
                        f"Chatwoot: messages hit the {MAX_MESSAGE_PAGES_PER_SYNC}-page aggregate cap; "
                        "rows beyond it were skipped"
                    )
                    return
                pages += 1
                pages_this_sync += 1
                url = _build_url(base_url, f"/conversations/{conversation_id}/messages", {"after": after})
                items = _extract_items(_fetch_json(session, url, logger), ("payload",), url)
                if not items:
                    break

                yield items

                page_max_id = max(item["id"] for item in items if item.get("id") is not None)
                if page_max_id <= after:
                    break  # server did not advance the cursor; bail rather than loop forever
                after = page_max_id
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
                # merge dedupes on the primary key.
                resumable_source_manager.save_state(ChatwootResumeConfig(conversation_id=conversation_id, after=after))

                if len(items) < MESSAGES_PAGE_SIZE:
                    break
            else:
                logger.warning(
                    f"Chatwoot: conversation {conversation_id} hit the "
                    f"{MAX_MESSAGE_PAGES_PER_CONVERSATION}-page message cap; rows beyond it were skipped"
                )
        except requests.HTTPError as exc:
            # A conversation deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Chatwoot: conversation {conversation_id} not found while fetching messages, skipping")
            else:
                raise

        # Advance the bookmark to the next conversation so a crash between conversations resumes
        # correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(ChatwootResumeConfig(conversation_id=remaining[index + 1], after=0))


def get_rows(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChatwootResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CHATWOOT_ENDPOINTS[endpoint]
    _ensure_host_allowed(host, team_id)
    base_url = _account_base_url(host, account_id)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = _make_session(api_access_token)

    if config.kind == "single":
        url = _build_url(base_url, config.path, dict(config.params))
        items = _extract_items(_fetch_json(session, url, logger), config.data_path, url)
        if items:
            yield items
        return

    if config.kind == "messages":
        yield from _get_message_rows(session, base_url, logger, resumable_source_manager)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page is not None else 1
    if resume is not None:
        logger.debug(f"Chatwoot: resuming {endpoint} from page {page}")

    while page <= MAX_LIST_PAGES:
        url = _build_url(base_url, config.path, {**config.params, "page": page})
        items = _extract_items(_fetch_json(session, url, logger), config.data_path, url)
        # Page sizes are fixed server-side but env-configurable on self-hosted installs, so the
        # only reliable end-of-collection signal is an empty page.
        if not items:
            return
        yield items
        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(ChatwootResumeConfig(page=page))
    logger.warning(f"Chatwoot: {endpoint} hit the {MAX_LIST_PAGES}-page cap; rows beyond it were skipped")


def _iso_to_epoch(value: Any) -> Any:
    """Webhook message payloads carry created_at as an ISO string; the REST API returns unix ints.
    Normalize so webhook rows merge into the same column type."""
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).timestamp())
        except ValueError:
            return value
    return value


def _maybe_json_loads(value: Any) -> Any:
    """Nested webhook payload fields round-trip through parquet as JSON strings."""
    if isinstance(value, str):
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return value
    return value


def _normalize_webhook_row(endpoint: str, row: dict[str, Any]) -> dict[str, Any] | None:
    """Reshape a webhook event body into the shape the pull path yields for `endpoint`.

    Webhook payloads put the object's attributes at the top level merged with an `event` key,
    plus `account`/`inbox` context objects the REST rows don't carry.
    """
    row = dict(row)
    row.pop("event", None)
    row.pop("account", None)
    row.pop("changed_attributes", None)

    if endpoint == "messages":
        row.pop("inbox", None)
        conversation = _maybe_json_loads(row.pop("conversation", None))
        if isinstance(conversation, dict) and row.get("conversation_id") is None:
            row["conversation_id"] = conversation.get("id")
        row["created_at"] = _iso_to_epoch(row.get("created_at"))
        message_type = row.get("message_type")
        if isinstance(message_type, str):
            row["message_type"] = MESSAGE_TYPE_TO_INT.get(message_type, message_type)

    if row.get("id") is None:
        return None
    return row


def make_webhook_table_transformer(endpoint: str) -> Callable[[pa.Table], pa.Table]:
    def transform(table: pa.Table) -> pa.Table:
        # Deduplicate by object id, keeping the last event in arrival order (the manager reads S3
        # files oldest-first). Multiple events (e.g. conversation_created then conversation_updated)
        # can reference the same object, and delta merge doesn't dedupe within a source batch.
        best_by_id: dict[Any, dict[str, Any]] = {}
        for raw_row in table.to_pylist():
            row = _normalize_webhook_row(endpoint, raw_row)
            if row is not None:
                best_by_id[row["id"]] = row
        return table_from_py_list(list(best_by_id.values()))

    return transform


def _list_webhooks(session: requests.Session, base_url: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    url = f"{base_url}/webhooks"
    data = _fetch_json(session, url, logger)
    if not isinstance(data, dict):
        return []
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return []
    webhooks = payload.get("webhooks")
    return webhooks if isinstance(webhooks, list) else []


def _find_webhook_by_url(
    session: requests.Session, base_url: str, webhook_url: str, logger: FilteringBoundLogger
) -> dict[str, Any] | None:
    return next((wh for wh in _list_webhooks(session, base_url, logger) if wh.get("url") == webhook_url), None)


def _read_json_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> tuple[int, Any]:
    """Status + parsed JSON body for webhook-management calls, with the same redirect refusal and
    capped body read as _fetch_json — the host is customer-controlled on these paths too, so the
    body must never be buffered unbounded."""
    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        raise ChatwootHostNotAllowedError(
            f"{HOST_NOT_ALLOWED_ERROR}: Chatwoot returned an unexpected redirect "
            f"(status={response.status_code}); refusing to follow it"
        )
    status = response.status_code
    body = _read_capped_body(response)
    if status >= 400:
        logger.error(f"Chatwoot API error: status={status}, body={body.decode(errors='replace')[:500]}, url={url}")
    try:
        return status, json.loads(body or b"null")
    except ValueError:
        return status, None


def _parse_webhook_response(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("webhook"), dict):
            return payload["webhook"]
    return {}


_WEBHOOK_PERMISSION_ERROR = (
    "Your Chatwoot API access token isn't allowed to manage webhooks — only administrator tokens "
    "can. Use an administrator's access token, or create the webhook manually."
)


def _webhook_creation_result_from_webhook(webhook: dict[str, Any]) -> WebhookCreationResult:
    secret = webhook.get("secret")
    if secret:
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    # Older self-hosted Chatwoot versions have no per-webhook secret and deliver unsigned
    # payloads; the user can either fill the secret in later or enable the bypass toggle.
    return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])


def create_webhook(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    webhook_url: str,
    team_id: int,
    logger: FilteringBoundLogger,
) -> WebhookCreationResult:
    try:
        _ensure_host_allowed(host, team_id)
        base_url = _account_base_url(host, account_id)
        session = _make_session(api_access_token)

        body = {"webhook": {"url": webhook_url, "subscriptions": all_webhook_events()}}
        create_url = f"{base_url}/webhooks"
        response = session.post(
            create_url, json=body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
        )
        status, data = _read_json_response(response, create_url, logger)

        if status in (401, 403):
            return WebhookCreationResult(success=False, error=_WEBHOOK_PERMISSION_ERROR)

        # Webhook URLs are unique per account, so re-registering after a partial setup 422s.
        # Reconcile the existing webhook instead of failing.
        if status == 422:
            existing = _find_webhook_by_url(session, base_url, webhook_url, logger)
            if existing is not None and existing.get("id") is not None:
                update_url = f"{base_url}/webhooks/{existing['id']}"
                update_response = session.patch(
                    update_url, json=body, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
                )
                update_status, update_data = _read_json_response(update_response, update_url, logger)
                if update_status in (401, 403):
                    return WebhookCreationResult(success=False, error=_WEBHOOK_PERMISSION_ERROR)
                if update_status >= 400:
                    raise Exception(f"Chatwoot webhook update failed with HTTP {update_status}")
                return _webhook_creation_result_from_webhook(_parse_webhook_response(update_data) or existing)

        if status >= 400:
            raise Exception(f"Chatwoot webhook creation failed with HTTP {status}")
        return _webhook_creation_result_from_webhook(_parse_webhook_response(data))
    except Exception as e:
        logger.exception(f"Chatwoot: failed to create webhook: {e}")
        return WebhookCreationResult(success=False, error=f"Failed to create Chatwoot webhook automatically: {e}")


def update_webhook_events(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    webhook_url: str,
    desired_events: list[str],
    team_id: int,
    logger: FilteringBoundLogger,
) -> WebhookSyncResult:
    try:
        _ensure_host_allowed(host, team_id)
        base_url = _account_base_url(host, account_id)
        session = _make_session(api_access_token)

        existing = _find_webhook_by_url(session, base_url, webhook_url, logger)
        if existing is None or existing.get("id") is None:
            return WebhookSyncResult(success=False, error="No Chatwoot webhook found for this source's webhook URL.")

        if sorted(existing.get("subscriptions") or []) == sorted(desired_events):
            return WebhookSyncResult(success=True)

        update_url = f"{base_url}/webhooks/{existing['id']}"
        response = session.patch(
            update_url,
            json={"webhook": {"url": webhook_url, "subscriptions": desired_events}},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        status, _ = _read_json_response(response, update_url, logger)
        if status in (401, 403):
            return WebhookSyncResult(success=False, error=_WEBHOOK_PERMISSION_ERROR)
        if status >= 400:
            raise Exception(f"Chatwoot webhook update failed with HTTP {status}")
        return WebhookSyncResult(success=True)
    except Exception as e:
        logger.exception(f"Chatwoot: failed to sync webhook events: {e}")
        return WebhookSyncResult(success=False, error=f"Failed to update Chatwoot webhook events: {e}")


def get_external_webhook_info(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    webhook_url: str,
    team_id: int,
    logger: FilteringBoundLogger,
) -> ExternalWebhookInfo:
    try:
        _ensure_host_allowed(host, team_id)
        base_url = _account_base_url(host, account_id)
        session = _make_session(api_access_token)

        existing = _find_webhook_by_url(session, base_url, webhook_url, logger)
        if existing is None:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=existing.get("url"),
            enabled_events=existing.get("subscriptions"),
            status="enabled",
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check Chatwoot webhook: {e}")


def delete_webhook(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    webhook_url: str,
    team_id: int,
    logger: FilteringBoundLogger,
) -> WebhookDeletionResult:
    try:
        _ensure_host_allowed(host, team_id)
        base_url = _account_base_url(host, account_id)
        session = _make_session(api_access_token)

        existing = _find_webhook_by_url(session, base_url, webhook_url, logger)
        if existing is None or existing.get("id") is None:
            # Nothing to delete — the desired end state already holds.
            return WebhookDeletionResult(success=True)

        delete_url = f"{base_url}/webhooks/{existing['id']}"
        response = session.delete(delete_url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True)
        status, _ = _read_json_response(response, delete_url, logger)
        if status in (401, 403):
            return WebhookDeletionResult(success=False, error=_WEBHOOK_PERMISSION_ERROR)
        if status >= 400:
            raise Exception(f"Chatwoot webhook deletion failed with HTTP {status}")
        return WebhookDeletionResult(success=True)
    except Exception as e:
        logger.exception(f"Chatwoot: failed to delete webhook: {e}")
        return WebhookDeletionResult(success=False, error=f"Failed to delete Chatwoot webhook: {e}")


def chatwoot_source(
    host: str | None,
    account_id: str | int | None,
    api_access_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChatwootResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
) -> SourceResponse:
    config: ChatwootEndpointConfig = CHATWOOT_ENDPOINTS[endpoint]

    webhook_enabled = (
        async_to_sync(webhook_source_manager.webhook_enabled)()
        if webhook_source_manager is not None and config.supports_webhooks
        else False
    )

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=make_webhook_table_transformer(endpoint))

        return get_rows(
            host=host,
            account_id=account_id,
            api_access_token=api_access_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
