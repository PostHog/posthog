from django.db import connection
from django.utils import timezone

from products.messaging.backend.facade.contracts import (
    CategoryMismatch,
    CodeSendCategory,
    MessageCategoryKind,
    RequestedCategory,
    SendCategory,
    SendCategoryDefinition,
    TooManyCategories,
)
from products.messaging.backend.models import MessageCategory

TRANSACTIONAL = "transactional"

SEND_CATEGORY_LIMIT = 100
SEND_CATEGORY_LOCK = "send-categories"


def requested_kind(requested: CodeSendCategory | RequestedCategory) -> MessageCategoryKind:
    return requested.type if isinstance(requested, SendCategoryDefinition) else "transactional"


def code_send_category(team_id: int, requested: CodeSendCategory) -> SendCategory | None:
    if not isinstance(requested, SendCategoryDefinition):
        return None
    category = _category_with_key(team_id, requested.key)
    if category is not None:
        _require_matching_type(category, requested)
        if not category.deleted:
            return SendCategory(id=category.id, type=requested.type)
    category = _create_or_restore(team_id, requested)
    return SendCategory(id=category.id, type=requested.type)


def template_send_category(
    loaded_category: MessageCategory | None, requested: CodeSendCategory | RequestedCategory
) -> SendCategory | None:
    if requested == "legacy":
        return None
    is_inherited = requested in (None, "inherit")
    if loaded_category is None:
        if is_inherited or requested == TRANSACTIONAL:
            return None
        if isinstance(requested, SendCategoryDefinition) and requested.type == "marketing":
            raise CategoryMismatch(
                "This template has no message category, so it can't send a marketing email. Use a different "
                "`template_key` for marketing code sends."
            )
        raise CategoryMismatch("This template has no message category. Leave `category` out, or send `transactional`.")
    if not is_inherited and not (
        isinstance(requested, SendCategoryDefinition)
        and requested.key == loaded_category.key
        and requested.type == loaded_category.category_type
    ):
        if isinstance(requested, SendCategoryDefinition) and requested.type == "marketing":
            raise CategoryMismatch(
                f"This template sends in the {loaded_category.category_type} category `{loaded_category.key}`, so "
                "it can't send a marketing email. Use a different `template_key` for marketing code sends."
            )
        raise CategoryMismatch(
            f"This template sends in the {loaded_category.category_type} category `{loaded_category.key}`. "
            f'Leave `category` out, or send `"key": "{loaded_category.key}"` with '
            f'`"type": "{loaded_category.category_type}"`.'
        )
    return SendCategory(id=loaded_category.id, type=_kind(loaded_category.category_type), inherited=is_inherited)


def _kind(category_type: str) -> MessageCategoryKind:
    return "marketing" if category_type == "marketing" else "transactional"


def _require_matching_type(category: MessageCategory, requested: SendCategoryDefinition) -> None:
    if category.category_type == requested.type:
        return
    if requested.type == "marketing":
        raise CategoryMismatch(
            f"The category `{requested.key}` is a {category.category_type} category, so it can't take a marketing "
            "email. Use another key for this marketing category."
        )
    raise CategoryMismatch(
        f"The category `{requested.key}` is a {category.category_type} category, so it can't take a transactional "
        f"email. Use another key, or send it as a {category.category_type} email if that's what you meant."
    )


def _category_with_key(team_id: int, key: str) -> MessageCategory | None:
    return MessageCategory.objects.filter(team_id=team_id, key=key).first()


def _lock_categories(team_id: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"{SEND_CATEGORY_LOCK}:{team_id}"])


def _create_or_restore(team_id: int, requested: SendCategoryDefinition) -> MessageCategory:
    assert connection.in_atomic_block
    _lock_categories(team_id)
    category = _category_with_key(team_id, requested.key)
    if category is not None:
        return _use_existing(team_id, category, requested)
    if (existing := _require_room_or_existing_live(team_id, requested)) is not None:
        return existing
    category, created = MessageCategory.objects.get_or_create(
        team_id=team_id,
        key=requested.key,
        defaults={
            "name": requested.name,
            "description": requested.description or "",
            "category_type": requested.type,
        },
    )
    if not created:
        return _use_existing(team_id, category, requested)
    return category


def _use_existing(team_id: int, category: MessageCategory, requested: SendCategoryDefinition) -> MessageCategory:
    _require_matching_type(category, requested)
    if category.deleted:
        if (existing := _require_room_or_existing_live(team_id, requested)) is not None:
            return existing
        MessageCategory.objects.filter(team_id=team_id, pk=category.pk, deleted=True).update(
            deleted=False, updated_at=timezone.now()
        )
    return category


def _require_room_or_existing_live(team_id: int, requested: SendCategoryDefinition) -> MessageCategory | None:
    if (
        MessageCategory.objects.filter(team_id=team_id, deleted=False).exclude(key=requested.key).count()
        < SEND_CATEGORY_LIMIT
    ):
        return None
    # The category management API doesn't take the send lock, so lock and re-read this key in case it just became live
    # while SEND_CATEGORY_LIMIT other categories are already live.
    existing = MessageCategory.objects.select_for_update().filter(team_id=team_id, key=requested.key).first()
    if existing is not None:
        _require_matching_type(existing, requested)
        if not existing.deleted:
            return existing
    raise _too_many_categories(requested.key)


def _too_many_categories(key: str) -> TooManyCategories:
    return TooManyCategories(
        f"This project has reached its limit of {SEND_CATEGORY_LIMIT} message categories, so a send can't "
        f"create the category `{key}`. Send the key of a category the project has, or archive categories it no "
        "longer uses."
    )
