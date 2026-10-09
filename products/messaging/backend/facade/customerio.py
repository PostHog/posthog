"""Customer.io sync setup: the App API import, the inbound webhook, the outbound Track API, and the CSV import."""

from typing import IO, Any

from posthog.dataclasses import frozen

from products.messaging.backend.services import customerio_config


class CustomerIOConfigConflict(Exception):
    """An integration of that kind already exists. The message tells the caller to delete it first."""


class CustomerIOConfigIncomplete(Exception):
    """The request lacks a credential the change needs. The message names it."""


@frozen
class SyncConfigState:
    app_integration_id: int | None
    app_import_result: dict[str, Any] | None
    csv_import_result: dict[str, Any] | None
    webhook_enabled: bool
    has_webhook_secret: bool
    track_enabled: bool
    has_track_credentials: bool


@frozen
class WebhookConfigState:
    webhook_enabled: bool
    has_webhook_secret: bool


@frozen
class TrackConfigState:
    track_enabled: bool
    has_track_credentials: bool


def import_from_customerio(team_id: int, app_api_key: str | None, created_by_id: int | None) -> dict[str, Any]:
    """Import topics and global unsubscribes from the App API. Stores the key on first use.

    Returns the import result as the API serves it. Raises CustomerIOConfigIncomplete without a key,
    and CustomerIOConfigConflict when a stored key exists and a new one is sent.
    """
    try:
        return customerio_config.import_from_customerio(team_id, app_api_key, created_by_id)
    except customerio_config.ConfigIncomplete as e:
        raise CustomerIOConfigIncomplete(str(e)) from e
    except customerio_config.ConfigConflict as e:
        raise CustomerIOConfigConflict(str(e)) from e


def get_sync_config_state(team_id: int) -> SyncConfigState:
    return SyncConfigState(**customerio_config.sync_config_state(team_id))


def remove_app_config(team_id: int) -> None:
    customerio_config.remove_app_config(team_id)


def save_webhook_config(
    team_id: int, signing_secret: str | None, enabled: bool, created_by_id: int | None
) -> WebhookConfigState:
    """Store the signing secret on first use, and turn the inbound webhook on or off."""
    try:
        saved = customerio_config.save_webhook_config(team_id, signing_secret, enabled, created_by_id)
    except customerio_config.ConfigIncomplete as e:
        raise CustomerIOConfigIncomplete(str(e)) from e
    except customerio_config.ConfigConflict as e:
        raise CustomerIOConfigConflict(str(e)) from e
    return WebhookConfigState(webhook_enabled=saved.enabled, has_webhook_secret=saved.has_credentials)


def remove_webhook_config(team_id: int) -> None:
    customerio_config.remove_webhook_config(team_id)


def save_track_config(
    team_id: int, site_id: str | None, api_key: str | None, region: str, enabled: bool, created_by_id: int | None
) -> TrackConfigState:
    """Store the Track API credentials on first use, and turn outbound sync on or off."""
    try:
        saved = customerio_config.save_track_config(team_id, site_id, api_key, region, enabled, created_by_id)
    except customerio_config.ConfigIncomplete as e:
        raise CustomerIOConfigIncomplete(str(e)) from e
    except customerio_config.ConfigConflict as e:
        raise CustomerIOConfigConflict(str(e)) from e
    return TrackConfigState(track_enabled=saved.enabled, has_track_credentials=saved.has_credentials)


def remove_track_config(team_id: int) -> None:
    customerio_config.remove_track_config(team_id)


def import_preferences_csv(team_id: int, csv_file: IO[bytes], created_by_id: int | None) -> dict[str, Any]:
    """Import recipient preferences from a Customer.io CSV export. Returns the result as the API serves it."""
    return customerio_config.import_preferences_csv(team_id, csv_file, created_by_id)
