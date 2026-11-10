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
    _update_to_match(category, requested)
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


def _create(team_id: int, requested: SendCategoryDefinition) -> MessageCategory:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{SEND_CATEGORY_LOCK}:{team_id}"])
        category = _category_with_key(team_id, requested.key)
        if category is not None:
            return category
        if MessageCategory.objects.filter(team_id=team_id, deleted=False).count() >= SEND_CATEGORY_LIMIT:
            raise TooManyCategories(
                f"This project has reached its limit of {SEND_CATEGORY_LIMIT} message categories, so a send can't "
                f"create the category `{requested.key}`. Send the key of a category the project has, or archive "
                "categories it no longer uses."
            )
        MessageCategory.objects.bulk_create(
            [
                MessageCategory(
                    team_id=team_id,
                    key=requested.key,
                    name=requested.name,
                    description=requested.description or "",
                    category_type=requested.type,
                )
            ],
            ignore_conflicts=True,
        )
        return MessageCategory.objects.get(team_id=team_id, key=requested.key)


def _update_to_match(category: MessageCategory, requested: SendCategoryDefinition) -> None:
    changes: dict[str, object] = {}
    if category.deleted:
        changes["deleted"] = False
    if category.name != requested.name:
        changes["name"] = requested.name
    if requested.description is not None and category.description != requested.description:
        changes["description"] = requested.description
    if changes:
        MessageCategory.objects.filter(team_id=category.team_id, pk=category.pk).update(
            **changes, updated_at=timezone.now()
        )
