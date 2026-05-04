import logging
from typing import Any

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig
from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOTrackClient

logger = logging.getLogger(__name__)


def _build_category_to_topic_map(team_id: int) -> dict[str, str]:
    """Map PostHog category UUID -> Customer.io topic key for customerio_* categories only."""
    categories = MessageCategory.objects.filter(team_id=team_id, key__startswith="customerio_", deleted=False)
    return {str(cat.id): cat.key.removeprefix("customerio_") for cat in categories}


def _get_track_client(config: OptOutSyncConfig) -> CustomerIOTrackClient | None:
    integration = config.track_integration
    if integration is None:
        return None
    site_id = integration.sensitive_config.get("site_id", "")
    api_key = integration.sensitive_config.get("api_key", "")
    region = integration.config.get("region", "us")
    if not site_id or not api_key:
        return None
    return CustomerIOTrackClient(site_id=site_id, api_key=api_key, region=region)


def sync_preferences_to_customerio(
    team_id: int,
    identifier: str,
    preferences: dict[str, Any],
) -> None:
    """Sync current preference state to Customer.io"""
    try:
        config = OptOutSyncConfig.objects.select_related("track_integration").get(team_id=team_id)
    except OptOutSyncConfig.DoesNotExist:
        return

    if not config.track_enabled or config.track_integration is None:
        return

    client = _get_track_client(config)
    if client is None:
        return

    category_to_topic = _build_category_to_topic_map(team_id)
    topic_prefs: dict[str, bool] = {}
    for category_id, topic_key in category_to_topic.items():
        status = preferences.get(category_id)
        if status is not None:
            topic_prefs[topic_key] = status != PreferenceStatus.OPTED_OUT.value

    try:
        if topic_prefs:
            client.update_subscription_preferences(identifier, topic_prefs)

        if ALL_MESSAGE_PREFERENCE_CATEGORY_ID in preferences:
            is_global_unsub = preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] == PreferenceStatus.OPTED_OUT.value
            client.set_global_unsubscribe(identifier, is_global_unsub)
    except CustomerIOAPIError:
        logger.exception(f"Failed to sync preferences to Customer.io for team {team_id}")
