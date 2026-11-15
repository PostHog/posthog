from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from products.messaging.backend.models.message_category import MessageCategory


def team_categories(team_id: int) -> QuerySet[MessageCategory]:
    return MessageCategory.objects.filter(team_id=team_id, deleted=False)


def team_category(team_id: int, category_id: UUID | str) -> MessageCategory:
    return team_categories(team_id).get(pk=category_id)


def key_in_use(team_id: int, key: str) -> bool:
    return MessageCategory.objects.filter(team_id=team_id, key=key, deleted=False).exists()


def create_category(team_id: int, created_by_id: int | None, fields: dict[str, Any]) -> MessageCategory:
    return MessageCategory.objects.create(**fields, team_id=team_id, created_by_id=created_by_id)


def update_category(team_id: int, category_id: UUID | str, fields: dict[str, Any]) -> MessageCategory:
    category = team_category(team_id, category_id)
    for attr, value in fields.items():
        setattr(category, attr, value)
    category.save()
    return category
