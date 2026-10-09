from typing import Any
from uuid import UUID

from products.messaging.backend.models import MessageCategory, MessageRecipientPreference, MessageTemplate


def create_message_category_for_test(*, team_id: int, key: str, name: str) -> UUID:
    return MessageCategory.objects.create(team_id=team_id, key=key, name=name).id


def create_recipient_preference_for_test(*, team_id: int, identifier: str, preferences: dict[str, str]) -> UUID:
    return MessageRecipientPreference.objects.create(team_id=team_id, identifier=identifier, preferences=preferences).id


def create_message_template_for_test(
    *, team_id: int, name: str, content: dict[str, Any], deleted: bool = False
) -> UUID:
    return MessageTemplate.objects.create(team_id=team_id, name=name, content=content, deleted=deleted).id
