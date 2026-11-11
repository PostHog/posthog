import logging
from typing import Any

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.models.optout_sync_config import OptOutSyncConfig

logger = logging.getLogger(__name__)


def signing_secret(team_id: int) -> tuple[str | None, int] | None:
    try:
        config = OptOutSyncConfig.objects.select_related("webhook_integration").get(team_id=team_id)
    except OptOutSyncConfig.DoesNotExist:
        return None
    if not config.webhook_enabled or not config.webhook_integration:
        return None
    integration = config.webhook_integration
    return integration.sensitive_config.get("webhook_signing_secret"), integration.id


def global_unsubscribe(team_id: int, email: str) -> None:
    recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)
    if recipient.preferences.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT.value:
        return
    recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value
    recipient.save(update_fields=["preferences", "updated_at"])


def global_resubscribe(team_id: int, email: str) -> None:
    recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)
    if ALL_MESSAGE_PREFERENCE_CATEGORY_ID in recipient.preferences:
        del recipient.preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
        recipient.save(update_fields=["preferences", "updated_at"])


def apply_topic_preferences(team_id: int, email: str, topics: dict[str, Any]) -> None:
    topic_key_to_category: dict[str, str] = {}
    categories = MessageCategory.objects.filter(team_id=team_id, key__startswith="customerio_", deleted=False)
    for cat in categories:
        topic_key = cat.key.removeprefix("customerio_")
        topic_key_to_category[topic_key] = str(cat.id)

    if not topic_key_to_category:
        return

    recipient, _ = MessageRecipientPreference.objects.get_or_create(team_id=team_id, identifier=email)

    changed = False
    for topic_key, is_subscribed in topics.items():
        category_id = topic_key_to_category.get(topic_key)
        if not category_id:
            logger.warning("customerio_webhook: unknown topic %s for team %s", topic_key, team_id)
            continue

        new_status = PreferenceStatus.OPTED_IN.value if is_subscribed else PreferenceStatus.OPTED_OUT.value
        if recipient.preferences.get(category_id) != new_status:
            recipient.preferences[category_id] = new_status
            changed = True

    if changed:
        recipient.save(update_fields=["preferences", "updated_at"])
