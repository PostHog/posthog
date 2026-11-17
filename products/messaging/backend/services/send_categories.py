from typing import Literal
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from products.messaging.backend.facade.contracts import (
    CategoryMismatch,
    MessageCategoryKind,
    SendCategory,
    SendCategoryDefinition,
    TooManyCategories,
)
from products.messaging.backend.models import MessageCategory

TRANSACTIONAL = "transactional"

RequestedCategory = Literal["transactional"] | SendCategoryDefinition | None

SEND_CATEGORY_LIMIT = 100
SEND_CATEGORY_LOCK = "send-categories"


def requested_kind(requested: RequestedCategory) -> MessageCategoryKind:
    return requested.type if isinstance(requested, SendCategoryDefinition) else "transactional"


def code_send_category(team_id: int, requested: RequestedCategory) -> SendCategory | None:
    if not isinstance(requested, SendCategoryDefinition):
        return None
    category = _category_with_key(team_id, requested.key) or _create(team_id, requested)
    if category.category_type != requested.type:
        raise CategoryMismatch(
            f"The category `{requested.key}` is a {category.category_type} category, so it can't take a "
            f'{requested.type} email. Send `"type": "{category.category_type}"`, or use another key.'
        )
    if category.deleted:
        _restore(team_id, category)
    return SendCategory(id=category.id, type=requested.type)


def template_send_category(
    template_category: MessageCategory | None, requested: RequestedCategory
) -> SendCategory | None:
    if template_category is None:
        if requested not in (None, TRANSACTIONAL):
            raise CategoryMismatch(
                "This template has no message category. Leave `category` out, or send `transactional`."
            )
        return None
    if requested is not None and not (
        isinstance(requested, SendCategoryDefinition)
        and requested.key == template_category.key
        and requested.type == template_category.category_type
    ):
        raise CategoryMismatch(
            f"This template sends in the {template_category.category_type} category `{template_category.key}`. "
            f'Leave `category` out, or send `"key": "{template_category.key}"` with '
            f'`"type": "{template_category.category_type}"`.'
        )
    return SendCategory(id=template_category.id, type=_kind(template_category.category_type))


def template_category(team_id: int, category_id: UUID | None) -> MessageCategory | None:
    if category_id is None:
        return None
    return MessageCategory.objects.filter(team_id=team_id, id=category_id).first()


def _kind(category_type: str) -> MessageCategoryKind:
    return "marketing" if category_type == "marketing" else "transactional"


def _category_with_key(team_id: int, key: str) -> MessageCategory | None:
    return MessageCategory.objects.filter(team_id=team_id, key=key).first()


def _lock_categories(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{SEND_CATEGORY_LOCK}:{team_id}"])


def _create(team_id: int, requested: SendCategoryDefinition) -> MessageCategory:
    with transaction.atomic():
        _lock_categories(team_id)
        if (category := _category_with_key(team_id, requested.key)) is not None:
            return category
        _require_room_for(team_id, requested.key)
        category, _created = MessageCategory.objects.get_or_create(
            team_id=team_id,
            key=requested.key,
            defaults={
                "name": requested.name,
                "description": requested.description or "",
                "category_type": requested.type,
            },
        )
        return category


def _require_room_for(team_id: int, key: str) -> None:
    if MessageCategory.objects.filter(team_id=team_id, deleted=False).count() >= SEND_CATEGORY_LIMIT:
        raise TooManyCategories(
            f"This project has reached its limit of {SEND_CATEGORY_LIMIT} message categories, so a send can't "
            f"create the category `{key}`. Send the key of a category the project has, or archive categories it no "
            "longer uses."
        )


def _restore(team_id: int, category: MessageCategory) -> None:
    with transaction.atomic():
        _lock_categories(team_id)
        archived = MessageCategory.objects.filter(team_id=team_id, pk=category.pk, deleted=True)
        if archived.exists():
            _require_room_for(team_id, category.key)
            archived.update(deleted=False, updated_at=timezone.now())
