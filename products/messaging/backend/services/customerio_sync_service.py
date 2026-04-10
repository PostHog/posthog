"""Customer.io unsubscribe sync.

Keeps PostHog's suppression list (``MessageRecipientPreference``) in sync with a team's
Customer.io workspace while campaigns migrate from Customer.io to PostHog. Two directions:

* **Outbound** — when a recipient opts out (via PostHog's managed preferences page or the
  one-click unsubscribe link), push ``unsubscribed=true`` to Customer.io via the Track API
  so campaigns still sending from Customer.io also respect the opt-out.
* **Inbound** — handled by the webhook endpoint in ``customerio_webhook.py``, which calls
  :func:`record_inbound_unsubscribe` to persist the opt-out locally.

Both directions are idempotent, so the sync loop (PostHog → CIO → PostHog webhook) is safe:
setting the same attribute again is a no-op on both sides.

The integration credentials (Site ID, Track API Key, region, webhook signing secret) are
stored on the shared ``Integration`` model with ``kind="customerio"`` — see the
:class:`CustomerIOSyncConfig` wrapper below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from posthog.models.integration import Integration

from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

from .customerio_client import CustomerIOAPIError, CustomerIOTrackClient

logger = logging.getLogger(__name__)

CUSTOMERIO_INTEGRATION_KIND = Integration.IntegrationKind.CUSTOMERIO.value


@dataclass
class CustomerIOSyncConfig:
    """Typed view over a team's Customer.io integration config."""

    integration: Integration

    @property
    def site_id(self) -> Optional[str]:
        return self.integration.config.get("site_id")

    @property
    def region(self) -> str:
        return self.integration.config.get("region", "us")

    @property
    def track_api_key(self) -> Optional[str]:
        return self.integration.sensitive_config.get("track_api_key")

    @property
    def webhook_signing_secret(self) -> Optional[str]:
        return self.integration.sensitive_config.get("webhook_signing_secret")

    @property
    def outbound_enabled(self) -> bool:
        """Outbound sync needs Track API credentials."""
        return bool(self.site_id and self.track_api_key)


def get_sync_config(team_id: int) -> Optional[CustomerIOSyncConfig]:
    """Return the active Customer.io sync config for a team, or None if none is configured.

    If a team has multiple Customer.io integration rows (shouldn't normally happen), the
    most recently created one wins.
    """
    integration = (
        Integration.objects.filter(team_id=team_id, kind=CUSTOMERIO_INTEGRATION_KIND).order_by("-created_at").first()
    )
    if integration is None:
        return None
    return CustomerIOSyncConfig(integration=integration)


def push_unsubscribe_to_customerio(team_id: int, identifier: str) -> bool:
    """Best-effort push of a single unsubscribe to Customer.io.

    Never raises — PostHog's own unsubscribe flow must always succeed even if the external
    sync is broken. Returns True on successful push, False otherwise (including when no
    integration is configured or outbound sync is disabled).
    """
    if not identifier:
        return False
    config = get_sync_config(team_id)
    if config is None or not config.outbound_enabled:
        return False

    try:
        client = CustomerIOTrackClient(
            site_id=config.site_id,  # type: ignore[arg-type]
            track_api_key=config.track_api_key,  # type: ignore[arg-type]
            region=config.region,
        )
        client.set_unsubscribed(identifier, unsubscribed=True)
        return True
    except (CustomerIOAPIError, ValueError):
        # Already logged inside the client; swallow so the caller can keep going.
        logger.exception(
            "Failed to push unsubscribe to Customer.io",
            extra={"team_id": team_id, "identifier_fingerprint": hash(identifier)},
        )
        return False
    except Exception:
        logger.exception(
            "Unexpected error pushing unsubscribe to Customer.io",
            extra={"team_id": team_id, "identifier_fingerprint": hash(identifier)},
        )
        return False


def record_inbound_unsubscribe(team_id: int, identifier: str) -> MessageRecipientPreference:
    """Mark ``identifier`` as globally opted-out locally in response to a Customer.io
    reporting webhook. Idempotent: repeated calls leave the row in the same state.
    """
    if not identifier:
        raise ValueError("identifier is required")

    recipient, _ = MessageRecipientPreference.objects.get_or_create(
        team_id=team_id,
        identifier=identifier,
        defaults={"preferences": {}},
    )

    recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value
    recipient.save(update_fields=["preferences", "updated_at"])
    return recipient
