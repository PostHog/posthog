"""Thin client for the Attentive REST API endpoints used by the data warehouse source.

Spec: https://docs.attentive.com/openapi/reference/
Attentive's public API is write-oriented; the only endpoints this source needs
are webhook management (`/v1/webhooks`) and the token probe (`/v2/me`).
"""

from typing import Any

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.attentive.constants import (
    ATTENTIVE_API_ORIGIN,
    ATTENTIVE_V1_BASE_URL,
    RESOURCE_TO_ATTENTIVE_EVENT_TYPE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

LOGGER = structlog.get_logger(__name__)

WEBHOOKS_URL = f"{ATTENTIVE_V1_BASE_URL}/webhooks"
REQUEST_TIMEOUT_SECONDS = 30


def _session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
    )


def _events_for_resources(resource_names: list[str]) -> list[str]:
    events: list[str] = []
    for resource in resource_names:
        event = RESOURCE_TO_ATTENTIVE_EVENT_TYPE.get(resource)
        if event is not None and event not in events:
            events.append(event)
    return events


def _format_http_error(error: requests.HTTPError) -> str:
    status_code = error.response.status_code
    if status_code == 401:
        return (
            "Attentive rejected the API key (401). Create a private app under Marketplace > "
            "Create app in Attentive and use its API key."
        )
    if status_code == 403:
        return "Attentive denied the request (403). Make sure the private app has the Webhooks permission."
    if status_code == 429:
        return "Attentive rate-limited the request (429). Try again in a few seconds."
    return f"Attentive API error ({status_code})."


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Validate the API key against Attentive's token-probe endpoint."""
    try:
        response = _session(api_key).get(f"{ATTENTIVE_API_ORIGIN}/v2/me", timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            response = _session(api_key).get(f"{ATTENTIVE_V1_BASE_URL}/me", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as e:
        return False, _format_http_error(e)
    except requests.RequestException as e:
        return False, f"Could not reach Attentive: {e}"
    return True, None


def _list_webhooks(api_key: str) -> list[dict[str, Any]]:
    response = _session(api_key).get(WEBHOOKS_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json() or {}
    raw = payload.get("webhooks") or []
    return [hook for hook in raw if isinstance(hook, dict)]


def _find_webhook_by_url(webhooks: list[dict[str, Any]], webhook_url: str) -> dict[str, Any] | None:
    for hook in webhooks:
        if hook.get("url") == webhook_url:
            return hook
    return None


def create_webhook(api_key: str, webhook_url: str, resource_names: list[str]) -> WebhookCreationResult:
    events = _events_for_resources(resource_names)
    if not events:
        supported = ", ".join(RESOURCE_TO_ATTENTIVE_EVENT_TYPE.keys())
        return WebhookCreationResult(
            success=False,
            error=f"None of the selected tables map to Attentive webhook events. Choose at least one of: {supported}.",
        )

    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key), webhook_url)
        if existing is not None:
            # Webhook already exists for this URL — treat as success so the user
            # can finish setup by entering the signing key.
            return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])

        session = _session(api_key)
        response = session.post(
            WEBHOOKS_URL,
            json={"url": webhook_url, "events": events},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        # Attentive has no create-disabled option, so immediately disable the
        # webhook until the user provides the signing key — otherwise events
        # would fire at PostHog before deliveries can be verified.
        webhook_id = (response.json() or {}).get("id")
        if not webhook_id:
            # The create response occasionally omits the id; look it up by URL so
            # we can still disable it rather than leaving an active webhook behind.
            created = _find_webhook_by_url(_list_webhooks(api_key), webhook_url)
            webhook_id = created.get("id") if created else None
        if not webhook_id:
            LOGGER.warning("Attentive webhook created but no id was returned; cannot disable it")
            return WebhookCreationResult(
                success=False,
                error=(
                    "Attentive created the webhook but did not return its id, so it could not be disabled "
                    "for signing-key setup. Please disable or delete the webhook in Attentive and try again."
                ),
            )
        session.put(
            f"{WEBHOOKS_URL}/{webhook_id}",
            json={"url": webhook_url, "events": events, "disabled": True},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).raise_for_status()
    except requests.HTTPError as e:
        LOGGER.warning("Failed to create Attentive webhook", error=str(e))
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        LOGGER.warning("Could not reach Attentive to create webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach Attentive: {e}")

    # Attentive does NOT return the signing key in the create response — the
    # user has to copy it from the webhook's settings in the Attentive UI.
    return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])


def enable_webhook(api_key: str, webhook_url: str) -> tuple[bool, str | None]:
    """Re-enable the webhook once the user has provided the signing key."""
    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key), webhook_url)
        if existing is None:
            return False, "No webhook found for this URL in Attentive."

        webhook_id = existing.get("id")
        if webhook_id is None:
            return False, "Attentive returned a webhook without an id; please enable it manually."

        _session(api_key).put(
            f"{WEBHOOKS_URL}/{webhook_id}",
            json={"url": webhook_url, "events": existing.get("events") or [], "disabled": False},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).raise_for_status()
    except requests.HTTPError as e:
        LOGGER.warning("Failed to enable Attentive webhook", error=str(e))
        return False, _format_http_error(e)
    except requests.RequestException as e:
        LOGGER.warning("Could not reach Attentive to enable webhook", error=str(e))
        return False, f"Could not reach Attentive: {e}"

    return True, None


def sync_webhook_events(api_key: str, webhook_url: str, resource_names: list[str]) -> WebhookSyncResult:
    """Reconcile the webhook's subscribed events with the selected schemas."""
    desired = _events_for_resources(resource_names)
    if not desired:
        return WebhookSyncResult(success=False, error="No selected tables map to Attentive webhook events.")

    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key), webhook_url)
        if existing is None:
            return WebhookSyncResult(success=False, error="No webhook found for this URL in Attentive.")

        current = existing.get("events") or []
        if set(current) == set(desired):
            return WebhookSyncResult(success=True)

        webhook_id = existing.get("id")
        if webhook_id is None:
            return WebhookSyncResult(success=False, error="Attentive returned a webhook without an id.")

        # Preserve the webhook's current disabled state — an events-only sync
        # must not silently re-enable a webhook that is still awaiting its signing key.
        _session(api_key).put(
            f"{WEBHOOKS_URL}/{webhook_id}",
            json={"url": webhook_url, "events": desired, "disabled": existing.get("disabledAt") is not None},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).raise_for_status()
    except requests.HTTPError as e:
        LOGGER.warning("Failed to sync Attentive webhook events", error=str(e))
        return WebhookSyncResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        LOGGER.warning("Could not reach Attentive to sync webhook events", error=str(e))
        return WebhookSyncResult(success=False, error=f"Could not reach Attentive: {e}")

    return WebhookSyncResult(success=True)


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        existing = _find_webhook_by_url(_list_webhooks(api_key), webhook_url)
        if existing is None:
            return WebhookDeletionResult(success=True)

        webhook_id = existing.get("id")
        if webhook_id is None:
            return WebhookDeletionResult(
                success=False, error="Attentive returned a webhook without an id; please delete it manually."
            )

        response = _session(api_key).delete(f"{WEBHOOKS_URL}/{webhook_id}", timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        LOGGER.warning("Failed to delete Attentive webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        LOGGER.warning("Could not reach Attentive to delete webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach Attentive: {e}")

    return WebhookDeletionResult(success=True)


def get_external_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        webhooks = _list_webhooks(api_key)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach Attentive: {e}")

    existing = _find_webhook_by_url(webhooks, webhook_url)
    if existing is None:
        return ExternalWebhookInfo(exists=False)

    enabled_events = existing.get("events")
    if not isinstance(enabled_events, list):
        enabled_events = None

    return ExternalWebhookInfo(
        exists=True,
        url=existing.get("url"),
        enabled_events=enabled_events,
        status="disabled" if existing.get("disabledAt") else "enabled",
    )
