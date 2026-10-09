"""Message categories: the per-team topics a recipient can opt out of."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.services import categories as categories_service
from products.messaging.backend.services.lazy_list import LazyList

MESSAGE_CATEGORY_TYPE_CHOICES: list[tuple[str, str]] = list(MessageCategoryType.choices)
DEFAULT_MESSAGE_CATEGORY_TYPE: str = MessageCategoryType.MARKETING.value


class MessageCategoryMissing(Exception):
    """The team has no category with that id that is not deleted, or the id is not a UUID."""


@frozen
class MessageCategoryRow:
    id: UUID
    key: str
    name: str
    description: str
    public_description: str
    category_type: str
    created_at: datetime
    updated_at: datetime
    created_by_id: int | None
    deleted: bool


def _to_contract(row: MessageCategory) -> MessageCategoryRow:
    return MessageCategoryRow(
        id=row.id,
        key=row.key,
        name=row.name,
        description=row.description,
        public_description=row.public_description,
        category_type=row.category_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by_id=row.created_by_id,
        deleted=row.deleted,
    )


def list_categories(team_id: int) -> Sequence[MessageCategoryRow]:
    """The team's categories that are not deleted. Sizing is a COUNT, and a slice reads one page."""
    # The mixin only adds its stable pk ordering to a QuerySet, so pages need it set here.
    return LazyList(categories_service.team_categories(team_id).order_by("pk"), _to_contract)


def get_category(team_id: int, category_id: UUID | str) -> MessageCategoryRow:
    try:
        return _to_contract(categories_service.team_category(team_id, category_id))
    except (MessageCategory.DoesNotExist, ValidationError, ValueError, TypeError) as e:
        raise MessageCategoryMissing() from e


def category_key_in_use(team_id: int, key: str) -> bool:
    """True when a category that is not deleted already uses the key."""
    return categories_service.key_in_use(team_id, key)


def create_category(team_id: int, created_by_id: int | None, fields: dict[str, Any]) -> MessageCategoryRow:
    return _to_contract(categories_service.create_category(team_id, created_by_id, fields))


def update_category(team_id: int, category_id: UUID, fields: dict[str, Any]) -> MessageCategoryRow:
    """Set the given fields and save the whole row, as the serializer's update did."""
    return _to_contract(categories_service.update_category(team_id, category_id, fields))
