from collections.abc import Iterator
from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from products.messaging.backend.models.message_category import MessageCategory, MessageCategoryType
from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.services.opt_out_service import BulkOptOutEntry, BulkOptOutResult, OptOutService
from products.messaging.backend.tasks import sync_preferences_to_customerio_task


class CategoryNotFound(Exception):
    pass


def _category(team_id: int, category_key: str) -> MessageCategory:
    category = MessageCategory.objects.filter(key=category_key, team_id=team_id).first()
    if category is None:
        raise CategoryNotFound()
    return category


def opted_out(team_id: int, category_key: str | None, search: str | None) -> QuerySet[MessageRecipientPreference]:
    # Find recipients who have opted out of this specific category, or use the derived $all category if no specific category is provided
    preference_key = str(_category(team_id, category_key).id) if category_key else ALL_MESSAGE_PREFERENCE_CATEGORY_ID

    opt_outs = MessageRecipientPreference.objects.filter(
        team_id=team_id,
        **{f"preferences__{preference_key}": PreferenceStatus.OPTED_OUT.value},
    )
    if search:
        opt_outs = opt_outs.filter(identifier__icontains=search)
    return opt_outs.order_by("-updated_at")  # Order by most recently updated first


def _sync_after_commit(team_id: int, identifier: str) -> None:
    # Customer.io round-trips can take tens of seconds, so sync off the request path
    # once the preference write has committed.
    transaction.on_commit(lambda: sync_preferences_to_customerio_task.delay(team_id, identifier))


def add_opt_out(
    team_id: int, identifier: str, category_key: str | None, created_by_id: int | None
) -> tuple[MessageRecipientPreference, bool]:
    category = _category(team_id, category_key) if category_key else None
    category_id = str(category.id) if category else ALL_MESSAGE_PREFERENCE_CATEGORY_ID

    preference, created = MessageRecipientPreference.objects.get_or_create(
        team_id=team_id,
        identifier=identifier,
        defaults={"created_by_id": created_by_id},
    )
    preference.set_preference(category_id, PreferenceStatus.OPTED_OUT)

    _sync_after_commit(team_id, identifier)
    return preference, created


def remove_opt_out(
    team_id: int, identifier: str, category_key: str | None, created_by_id: int | None
) -> tuple[MessageRecipientPreference, bool]:
    category = _category(team_id, category_key) if category_key else None

    preference, created = MessageRecipientPreference.objects.get_or_create(
        team_id=team_id,
        identifier=identifier,
        defaults={"created_by_id": created_by_id},
    )
    preferences = dict(preference.preferences or {})

    if category is None:
        preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_IN.value
    else:
        _lift_global_opt_out(team_id, preferences, category)
        preferences[str(category.id)] = PreferenceStatus.OPTED_IN.value

    preference.preferences = preferences
    preference.save(update_fields=["preferences", "updated_at"])

    _sync_after_commit(team_id, identifier)
    return preference, created


def _lift_global_opt_out(team_id: int, preferences: dict[str, Any], category: MessageCategory) -> None:
    """Clear a `$all` opt-out that would otherwise swallow a per-category resubscribe.

    Sends check the category and `$all` together, so opting someone back in to one category
    does nothing while `$all` stays opted out. Pin the team's other marketing categories to
    opted out first, so lifting `$all` resubscribes only the category the caller named
    instead of silently widening consent to everything.

    The pinning overwrites even an explicit OPTED_IN on a sibling category (e.g. one a
    Customer.io webhook recorded): while `$all` was opted out that opt-in was inert, so
    preserving the recipient's effective state means opting the sibling out, not letting
    the stale opt-in spring back to life.
    """
    if category.category_type != MessageCategoryType.MARKETING:
        return
    if preferences.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) != PreferenceStatus.OPTED_OUT.value:
        return

    other_category_ids = (
        MessageCategory.objects.filter(team_id=team_id, category_type=MessageCategoryType.MARKETING, deleted=False)
        .exclude(id=category.id)
        .values_list("id", flat=True)
    )
    for other_category_id in other_category_ids:
        preferences[str(other_category_id)] = PreferenceStatus.OPTED_OUT.value

    preferences[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_IN.value


def export_rows(team_id: int, category_key: str | None) -> Iterator[str]:
    return OptOutService(team_id=team_id).export_rows(category_key)


def bulk_opt_out(
    team_id: int, entries: list[BulkOptOutEntry], default_category_key: str | None, created_by_id: int | None
) -> BulkOptOutResult:
    return OptOutService(team_id=team_id, created_by_id=created_by_id).opt_out_recipients(entries, default_category_key)
