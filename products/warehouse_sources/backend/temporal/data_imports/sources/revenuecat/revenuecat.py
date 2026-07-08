"""Thin RevenueCat API v2 client used by the data warehouse source.

Spec: https://www.revenuecat.com/docs/api-v2

Everything in this module routes through ``make_tracked_session`` so outbound
calls show up in our HTTP logs, OTel metrics, and sample-capture pipeline.
"""

import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode, urljoin

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    REVENUECAT_API_BASE_URL,
    REVENUECAT_AUTO_WEBHOOK_NAME,
    REVENUECAT_WEBHOOK_EVENT_TYPES,
)

LOGGER = structlog.get_logger(__name__)

DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class RevenueCatResumeConfig:
    """Cursor state for resumable list iteration.

    ``starting_after`` is the RevenueCat-issued cursor value (the id of the last
    item from the previous page). ``endpoint`` scopes the cursor to a single
    endpoint so we never replay a customers cursor against products.
    """

    endpoint: str
    starting_after: str


def _auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _session(api_key: str) -> requests.Session:
    return make_tracked_session(headers=_auth_headers(api_key))


def _project_path(project_id: str, suffix: str) -> str:
    return f"/projects/{project_id}{suffix}"


# How many accessible project ids we list back when an entered id 404s. Most keys
# see a single project, so this is really just a guard against a wall of text.
MAX_SUGGESTED_PROJECTS = 5


def _normalize_project_id(raw: str | None) -> str:
    """Best-effort cleanup of a user-entered RevenueCat project id.

    The setup form points users at their dashboard URL
    (``app.revenuecat.com/projects/<project_id>``) to find the id, so a large
    share of connection failures come from pasting the whole URL, a
    ``projects/<id>`` path fragment, a value with stray whitespace, or the bare
    id with its ``proj`` prefix dropped. Pull the id back out, trim it, and
    restore a missing prefix so those copy-paste mistakes don't become a 404.
    """
    if not raw:
        return ""
    value = raw.strip()
    # Pasted a full or partial dashboard URL / `.../projects/<id>/...` path. The
    # marker has no leading slash so it matches both `/projects/x` and the
    # bare `projects/x` form.
    marker = "projects/"
    if marker in value:
        value = value.split(marker, 1)[1]
    # Keep only the first path segment, dropping any trailing `/overview`,
    # query string, or fragment that rode along with the paste.
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].strip()
    # RevenueCat project ids are always `proj`-prefixed (e.g. `proj1a2b3c4d`),
    # but the setup form points users at the dashboard where the id is shown
    # without the prefix, so a large share of failures are bare ids like
    # `1a2b3c4d`. Restore the prefix so that copy-paste slip isn't a dead-end
    # 404 — the membership check against the live project list still rejects
    # anything that isn't a real, reachable project.
    if value and not value.startswith("proj"):
        value = f"proj{value}"
    return value


def _accessible_project_ids(payload: dict[str, Any] | None) -> list[str]:
    """Pull the project ids out of a ``GET /v2/projects`` response page.

    We deliberately keep only the ids (opaque ``proj...`` tokens), never the
    project names — the error string built from this is captured into our
    analytics, and names can carry a customer's app/company identity.
    """
    items = (payload or {}).get("items")
    if not isinstance(items, list):
        return []
    return [str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")]


def _list_accessible_project_ids(session: requests.Session) -> list[str] | None:
    """Return every project id the key can see, following cursor pages.

    Returns ``None`` when a page comes back 200 but unparseable — callers can't
    distinguish "no projects" from "couldn't read the list", and the two demand
    opposite treatment, so we surface the difference. HTTP/network errors
    propagate to the caller.
    """
    ids: list[str] = []
    url = f"{REVENUECAT_API_BASE_URL}/projects"
    params: dict[str, Any] | None = {"limit": DEFAULT_PAGE_SIZE}

    while True:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        try:
            payload = response.json() or {}
        except (ValueError, requests.exceptions.JSONDecodeError):
            return None

        ids.extend(_accessible_project_ids(payload))

        next_page = payload.get("next_page")
        if not next_page:
            return ids
        # next_page already carries its own query string — see iterate_list_endpoint.
        url = next_page if next_page.startswith("http") else urljoin(REVENUECAT_API_BASE_URL, next_page)
        params = None


def _project_not_found_error(entered_project_id: str, accessible_ids: list[str]) -> str:
    """Turn an opaque 404 into an actionable message naming the reachable project ids."""
    if not accessible_ids:
        return (
            f"RevenueCat could not find the project '{entered_project_id}' (404), and this API key "
            "can't see any projects. Generate a v2 secret API key in the RevenueCat project you want "
            "to sync, then re-enter its Project ID."
        )
    if len(accessible_ids) == 1:
        only = accessible_ids[0]
        return (
            f"RevenueCat has no project '{entered_project_id}' for this API key. The key has access to "
            f"one project — '{only}'. Set the Project ID to '{only}' and reconnect."
        )
    shown = accessible_ids[:MAX_SUGGESTED_PROJECTS]
    listed = ", ".join(f"'{pid}'" for pid in shown)
    overflow = len(accessible_ids) - MAX_SUGGESTED_PROJECTS
    more = f" (+{overflow} more)" if overflow > 0 else ""
    return (
        f"RevenueCat has no project '{entered_project_id}' for this API key. The key has access to: "
        f"{listed}{more}. Copy the exact Project ID from your RevenueCat dashboard and reconnect."
    )


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    status_code = response.status_code if response is not None else None
    if status_code == 401:
        return (
            "RevenueCat rejected the API key (401). Generate a v2 secret API key "
            "from Project settings > API keys and check that it has not been revoked."
        )
    if status_code == 403:
        return (
            "RevenueCat denied the request (403). Make sure the v2 secret API key "
            "has the permissions required for this resource."
        )
    if status_code == 404:
        return "RevenueCat could not find the project (404). Double-check the project id."
    if status_code == 429:
        return "RevenueCat rate-limited the request (429). Try again in a few seconds."
    return f"RevenueCat API error ({status_code})."


def validate_credentials(api_key: str, project_id: str | None) -> tuple[bool, str | None]:
    """Confirm the key works and (when set) that it can reach ``project_id``.

    ``GET /v2/projects`` both validates the key and tells us every project the
    key can see, so the project check is a membership test against that list.
    There is no ``GET /v2/projects/{id}`` endpoint in the RevenueCat v2 API —
    probing it 404s even for a perfectly valid id, so never "verify" a project
    that way. The entered id is normalized first so a pasted dashboard URL or
    stray whitespace doesn't masquerade as a missing project; on a miss, the
    error names the project ids the key *can* reach instead of a dead-end
    "double-check the project id".
    """
    session = _session(api_key)
    try:
        accessible_ids = _list_accessible_project_ids(session)
    except requests.HTTPError as e:
        return False, _format_http_error(e)
    except requests.RequestException as e:
        return False, f"Could not reach RevenueCat: {e}"

    normalized_project_id = _normalize_project_id(project_id)
    if not normalized_project_id:
        return True, None

    # The list came back 200 but unreadable — the key itself is good, and we
    # have no way to check the project, so fail open rather than block setup.
    if accessible_ids is None:
        return True, None

    if normalized_project_id in accessible_ids:
        return True, None
    return False, _project_not_found_error(normalized_project_id, accessible_ids)


def _ms_to_seconds(value: Any) -> Any:
    """Convert a millisecond epoch int to a Unix-seconds int.

    RevenueCat returns timestamps as millisecond epochs (e.g. ``1658399423658``),
    but the warehouse partition layer interprets bare ints as Unix *seconds*
    (``datetime.datetime.fromtimestamp(date)``). Normalize to seconds so a
    datetime partition on ``created_at`` produces sane bucket dates, matching
    the convention used by other sources (Stripe's ``created`` is already in
    seconds).
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return value // 1000
    return value


def iterate_list_endpoint(
    api_key: str,
    project_id: str,
    path_suffix: str,
    *,
    endpoint_name: str,
    timestamp_fields: tuple[str, ...] = ("created_at",),
    starting_after: str | None = None,
    on_cursor_advance: Callable[[str, str], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield rows from a RevenueCat v2 list endpoint, transparently following the cursor.

    RevenueCat returns ``{"items": [...], "next_page": "/v2/path?starting_after=ID"}``.
    When ``next_page`` is null/absent, the list is exhausted.

    Rows are normalized in flight: any ms-epoch field named in ``timestamp_fields``
    is divided by 1000 so it lands in the warehouse as a Unix-seconds int the
    partition layer can interpret directly. This must cover the endpoint's
    partition key — which is ``created_at`` for most endpoints but ``first_seen_at``
    for customers (the customer object has no ``created_at``). See ``_ms_to_seconds``.

    ``on_cursor_advance`` is invoked with the last item's id every time we finish
    yielding a page so callers (e.g. the resumable manager) can checkpoint. We
    save state *after* yielding so a crash re-yields the last page rather than
    skipping it — merge dedupes on primary key.
    """
    project_id = _normalize_project_id(project_id)
    session = _session(api_key)
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    if starting_after:
        params["starting_after"] = starting_after

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, path_suffix)}"

    while True:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}

        rows = payload.get("items") or []
        if not isinstance(rows, list):
            return

        last_id: str | None = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field in timestamp_fields:
                if field in row:
                    row[field] = _ms_to_seconds(row[field])
            yield row
            # `id` is the declared primary key for every RevenueCat list
            # endpoint (see settings.py). Access it directly so a malformed
            # response missing `id` raises `KeyError` here rather than
            # silently advancing the cursor to a stale value — which would
            # corrupt the merge/dedupe step downstream.
            last_id = row["id"]

        next_page = payload.get("next_page")
        if last_id is not None and on_cursor_advance is not None:
            on_cursor_advance(endpoint_name, last_id)

        if not next_page:
            return

        # next_page is a relative path including its own query string (e.g.
        # `/v2/projects/{id}/customers?starting_after=cus_abc&limit=20`). The
        # path already encodes the next cursor, so re-send it as-is with no
        # extra params — passing both `params=` and a query-bearing url would
        # produce duplicate `limit=` values.
        url = next_page if next_page.startswith("http") else urljoin(REVENUECAT_API_BASE_URL, next_page)
        params = {}


def create_webhook(
    api_key: str,
    project_id: str,
    webhook_url: str,
    authorization_header_value: str | None = None,
) -> WebhookCreationResult:
    """Auto-register a webhook integration in RevenueCat pointing at ``webhook_url``.

    Auth-header note: RevenueCat does not HMAC-sign its webhook deliveries —
    instead, the integration ships an ``Authorization`` header whose value the
    user sets at creation time. We let callers pass that value through so we
    can later verify it in the Hog template. If not supplied, the integration
    is created without an auth header and the user finishes setup by adding one
    via the webhook fields (handled by the surrounding warehouse-source flow).
    """
    project_id = _normalize_project_id(project_id)
    logger = LOGGER.bind(project_id=project_id)

    body: dict[str, Any] = {
        "url": webhook_url,
        "events": list(REVENUECAT_WEBHOOK_EVENT_TYPES),
        "name": REVENUECAT_AUTO_WEBHOOK_NAME,
    }
    if authorization_header_value:
        # RevenueCat names this field `signing_secret` in their API even though
        # the upstream behavior is just "send this verbatim as Authorization".
        body["signing_secret"] = authorization_header_value

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, '/integrations/webhook')}"

    try:
        existing = _find_webhook_integration(api_key, project_id, webhook_url)
        if existing is not None:
            if authorization_header_value:
                # We were asked to bind a new authorization header but a webhook
                # already exists. RevenueCat has no in-place update for the
                # auth header — surface a failure so the caller (typically
                # `webhook_inputs_updated`) can drive an explicit delete +
                # recreate instead of silently leaving the existing webhook
                # bound to a stale header.
                return WebhookCreationResult(
                    success=False,
                    error=(
                        "A RevenueCat webhook integration already exists for this URL. "
                        "Delete it and reconnect to bind a new authorization header."
                    ),
                )
            # No auth header supplied yet — treat the existing webhook as
            # success so the user can finish setup by entering the header
            # value. RevenueCat omits the configured header from list
            # responses, so we can't tell whether one is already set.
            return WebhookCreationResult(success=True, pending_inputs=["authorization_header"])

        response = _session(api_key).post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to create RevenueCat webhook integration", error=str(e))
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to create webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach RevenueCat: {e}")

    pending: list[str] = []
    if not authorization_header_value:
        pending.append("authorization_header")
    return WebhookCreationResult(success=True, pending_inputs=pending)


def _list_webhook_integrations(api_key: str, project_id: str) -> list[dict[str, Any]]:
    """Iterate the webhook integrations under a project, following cursor pages."""
    items: list[dict[str, Any]] = []
    session = _session(api_key)
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, '/integrations/webhook')}"

    while True:
        # Build the URL with explicit query encoding so the call signature stays
        # stable across pages and we never accidentally pass duplicate `limit`s.
        request_url = f"{url}?{urlencode(params)}" if params else url
        response = session.get(request_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json() or {}

        page = payload.get("items") or []
        if isinstance(page, list):
            for hook in page:
                if isinstance(hook, dict):
                    items.append(hook)

        next_page = payload.get("next_page")
        if not next_page:
            return items
        url = next_page if next_page.startswith("http") else urljoin(REVENUECAT_API_BASE_URL, next_page)
        params = {}


def _find_webhook_integration(api_key: str, project_id: str, webhook_url: str) -> dict[str, Any] | None:
    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.RequestException:
        return None
    for hook in integrations:
        if hook.get("url") == webhook_url:
            return hook
    return None


def delete_webhook(api_key: str, project_id: str, webhook_url: str) -> WebhookDeletionResult:
    project_id = _normalize_project_id(project_id)
    logger = LOGGER.bind(project_id=project_id)

    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.HTTPError as e:
        logger.warning("Failed to list RevenueCat webhook integrations", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to list webhooks", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach RevenueCat: {e}")

    target = next((hook for hook in integrations if hook.get("url") == webhook_url), None)
    if target is None:
        # Nothing to delete is a success — keep delete idempotent.
        return WebhookDeletionResult(success=True)

    webhook_id = target.get("id")
    if not webhook_id:
        return WebhookDeletionResult(
            success=False,
            error="RevenueCat returned a webhook without an id; please delete it manually.",
        )

    url = f"{REVENUECAT_API_BASE_URL}{_project_path(project_id, f'/integrations/webhook/{webhook_id}')}"
    try:
        response = _session(api_key).delete(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to delete RevenueCat webhook integration", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach RevenueCat to delete webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach RevenueCat: {e}")

    return WebhookDeletionResult(success=True)


def _webhook_status_http_error(api_key: str, project_id: str, error: requests.HTTPError) -> str:
    """Build the status-check message for an HTTP error listing webhook integrations.

    The 404 case is the reason this exists. ``GET /projects/{id}/integrations/webhook``
    returns 404 for a wrong project id, but a source only reaches the webhook
    *status* check after ``validate_credentials`` already confirmed the id is
    reachable — so the generic "double-check the project id" text (see
    ``_format_http_error``) is a false alarm that sends users to re-check a
    correct value. Re-run the membership test: only name the project id as the
    problem when it genuinely isn't reachable; otherwise make clear the id is
    fine and that an unreadable webhook status doesn't stop ingestion.
    """
    response = error.response
    status_code = response.status_code if response is not None else None
    if status_code != 404:
        return _format_http_error(error)

    try:
        accessible_ids = _list_accessible_project_ids(_session(api_key))
    except requests.RequestException:
        accessible_ids = None

    # A readable list that omits the project means the id really is wrong — name
    # the ids the key can reach, same as validate_credentials does.
    if accessible_ids is not None and project_id not in accessible_ids:
        return _project_not_found_error(project_id, accessible_ids)

    # Project is reachable (or we couldn't tell): the 404 is about the webhook
    # integration, not the project. Don't impugn a valid id, and reassure that
    # ingestion is unaffected — events still flow through the processing path.
    return (
        "RevenueCat returned a 404 for the webhook integration. Your project id is valid, so this "
        "does not affect data ingestion — events still flow through the processing pipeline. The "
        "webhook status just can't be read right now; if you registered the webhook manually, no "
        "action is needed."
    )


def get_external_webhook_info(api_key: str, project_id: str, webhook_url: str) -> ExternalWebhookInfo:
    project_id = _normalize_project_id(project_id)
    try:
        integrations = _list_webhook_integrations(api_key, project_id)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_webhook_status_http_error(api_key, project_id, e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach RevenueCat: {e}")

    target = next((hook for hook in integrations if hook.get("url") == webhook_url), None)
    if target is None:
        return ExternalWebhookInfo(exists=False)

    events_value = target.get("events")
    enabled_events = events_value if isinstance(events_value, list) else None
    created_at_raw = target.get("created_at")
    created_at = str(created_at_raw) if created_at_raw is not None else None

    return ExternalWebhookInfo(
        exists=True,
        url=target.get("url"),
        enabled_events=enabled_events,
        # RevenueCat doesn't expose an enabled/disabled state on the integration
        # object — once created, it's active. Report "enabled" to surface that.
        status="enabled",
        description=target.get("name"),
        created_at=created_at,
    )
