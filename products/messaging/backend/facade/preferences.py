"""Recipient opt-outs: who opted out of which message category, and changes to that list."""

from collections.abc import Iterator, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from products.messaging.backend.models import message_preferences as preference_model
from products.messaging.backend.models.message_preferences import MessageRecipientPreference
from products.messaging.backend.services import (
    customerio_sync_service,
    preferences as preferences_service,
)
from products.messaging.backend.services.lazy_list import LazyList
from products.messaging.backend.services.opt_out_service import BulkOptOutEntry, UnknownCategoryError

ALL_MESSAGE_PREFERENCE_CATEGORY_ID: str = preference_model.ALL_MESSAGE_PREFERENCE_CATEGORY_ID
EMAIL_TRACKING_PREFERENCE_ID: str = preference_model.EMAIL_TRACKING_PREFERENCE_ID


class PreferenceStatus(StrEnum):
    """The stored value of one preference. Mirrors the model's choices."""

    OPTED_IN = "OPTED_IN"
    OPTED_OUT = "OPTED_OUT"
    NO_PREFERENCE = "NO_PREFERENCE"


class MessageCategoryNotFound(Exception):
    """No category with the requested key exists for the team. The message names the key when known."""


@frozen
class RecipientPreferences:
    id: UUID
    identifier: str
    updated_at: datetime
    # Category id (or the reserved `$all` key) to OPTED_IN, OPTED_OUT or NO_PREFERENCE.
    preferences: dict[str, Any]


@frozen
class ChangedPreferences:
    preferences: RecipientPreferences
    created: bool


@frozen
class OptOutRequest:
    identifier: str
    category_key: str | None = None


@frozen
class BulkOptOutOutcome:
    total: int
    opted_out: int
    skipped: int
    errors: list[str]


def _to_contract(row: MessageRecipientPreference) -> RecipientPreferences:
    return RecipientPreferences(
        id=row.id, identifier=row.identifier, updated_at=row.updated_at, preferences=row.preferences
    )


def list_opt_outs(team_id: int, category_key: str | None, search: str | None) -> Sequence[RecipientPreferences]:
    """Recipients opted out of the category, or of all marketing when no key is given. Most recent first.

    Sizing is a COUNT, and a slice reads one page. Raises MessageCategoryNotFound for an unknown key.
    """
    try:
        rows = preferences_service.opted_out(team_id, category_key, search)
    except preferences_service.CategoryNotFound as e:
        raise MessageCategoryNotFound("Category not found") from e
    return LazyList(rows, _to_contract)


def add_opt_out(
    team_id: int, identifier: str, category_key: str | None, created_by_id: int | None
) -> ChangedPreferences:
    """Opt the recipient out of the category, or of all marketing. Syncs to Customer.io after commit."""
    try:
        row, created = preferences_service.add_opt_out(team_id, identifier, category_key, created_by_id)
    except preferences_service.CategoryNotFound as e:
        raise MessageCategoryNotFound("Category not found") from e
    return ChangedPreferences(preferences=_to_contract(row), created=created)


def remove_opt_out(
    team_id: int, identifier: str, category_key: str | None, created_by_id: int | None
) -> ChangedPreferences:
    """Opt the recipient back in, lifting a global opt-out without widening it. Syncs after commit."""
    try:
        row, created = preferences_service.remove_opt_out(team_id, identifier, category_key, created_by_id)
    except preferences_service.CategoryNotFound as e:
        raise MessageCategoryNotFound("Category not found") from e
    return ChangedPreferences(preferences=_to_contract(row), created=created)


def export_opt_outs_csv(team_id: int, category_key: str | None) -> Iterator[str]:
    """CSV rows of the opt-out list, in the format the CSV import reads back."""
    try:
        return preferences_service.export_rows(team_id, category_key)
    except UnknownCategoryError as e:
        raise MessageCategoryNotFound(str(e)) from e


def bulk_opt_out(
    team_id: int, requests: list[OptOutRequest], default_category_key: str | None, created_by_id: int | None
) -> BulkOptOutOutcome:
    """Opt every recipient out of its own category, or the default one. Unknown categories are skipped."""
    entries = [BulkOptOutEntry(identifier=r.identifier, category_key=r.category_key) for r in requests]
    try:
        result = preferences_service.bulk_opt_out(team_id, entries, default_category_key, created_by_id)
    except UnknownCategoryError as e:
        raise MessageCategoryNotFound(str(e)) from e
    return BulkOptOutOutcome(
        total=result.total, opted_out=result.opted_out, skipped=result.skipped, errors=result.errors
    )


@frozen
class CategoryOption:
    id: UUID
    name: str
    public_description: str


def preference_status(preferences: dict[str, Any], category_id: str) -> PreferenceStatus:
    """The status stored for one category. Raises ValueError for a value that is not a status."""
    return PreferenceStatus(preferences.get(str(category_id), PreferenceStatus.NO_PREFERENCE.value))


def all_preference_statuses(preferences: dict[str, Any]) -> dict[str, PreferenceStatus]:
    """Every stored status by category id. Raises ValueError for a value that is not a status."""
    return {str(category_id): PreferenceStatus(status) for category_id, status in preferences.items()}


def category_ids(team_id: int) -> set[str]:
    """Ids of the team's categories that are not deleted, of every type."""
    return preferences_service.category_ids(team_id)


def marketing_categories(team_id: int) -> list[CategoryOption]:
    """The team's marketing categories that are not deleted, by name."""
    return [
        CategoryOption(id=c.id, name=c.name, public_description=c.public_description)
        for c in preferences_service.marketing_categories(team_id)
    ]


def get_or_create_recipient(team_id: int, identifier: str) -> RecipientPreferences:
    return _to_contract(preferences_service.get_or_create_recipient(team_id, identifier))


def recipient_preferences(team_id: int, identifier: str) -> dict[str, Any] | None:
    """The recipient's stored preferences, or None when the team has no row for them."""
    row = preferences_service.recipient_or_none(team_id, identifier)
    return None if row is None else row.preferences


def set_preferences_column(team_id: int, identifier: str, preferences: dict[str, Any]) -> None:
    """Overwrite an existing recipient's preferences. Writes only that column, so updated_at stays."""
    preferences_service.set_preferences_column(team_id, identifier, preferences)


def replace_preferences(team_id: int, identifier: str, preferences: dict[str, Any]) -> None:
    """Overwrite the recipient's preferences with one full save, creating the row when it is missing."""
    preferences_service.replace_preferences(team_id, identifier, preferences)


def sync_to_customerio(team_id: int, identifier: str, preferences: dict[str, Any]) -> None:
    """Push the preferences to Customer.io now, when the team has track sync enabled."""
    customerio_sync_service.sync_preferences_to_customerio(team_id, identifier, preferences)
