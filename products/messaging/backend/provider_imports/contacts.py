"""Contact steps every provider import shares: each list of contacts becomes people and fills a cohort."""

import re
from collections.abc import Iterable, Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportItem,
    ImportStepError,
    ImportStepSpec,
    SavedPage,
)
from products.messaging.backend.provider_imports.emails import exact_email
from products.workflows.backend.facade.contracts import ProviderContactsResult
from products.workflows.backend.facade.people_import import MAX_PEOPLE_IMPORT_ROW_BYTES, import_provider_contacts

NEW_PEOPLE_STEP = "new_people"
# Person properties hold short values, so a provider's longer custom field is left out rather than cut.
MAX_PROPERTY_VALUE_LENGTH = 1000
# Contacts plus list memberships one step reads. Every list's contacts stay in memory until the step saves.
MAX_CONTACT_MEMBERSHIPS = 250_000
MAX_CONTACT_BYTES = 200 * 1024 * 1024
MAX_PROPERTY_NAME_LENGTH = 200
TOO_MANY_CONTACTS_MESSAGE = (
    "This account has more contacts, list memberships or contact data than one import takes. Upload your people as "
    "a CSV file instead."
)
# The people import reads these names as the person to write to, so a provider field can't use them.
_IDENTITY_NAMES = frozenset({"email", "id", "distinct_id"})
_NAME_SEPARATORS = re.compile(r"[^a-z0-9]+")

CONTACT_COUNT_LABELS = (
    ("people", "Contacts sent to PostHog"),
    ("new_people", "New people"),
    ("skipped_new_people", "No matching person, left out"),
    ("dropped", "Skipped because the address isn't valid or repeats"),
)


@frozen
class ContactList:
    """One list or segment of contacts, and the cohort its contacts go into."""

    cohort_name: str
    # Finds the cohort again on a rerun, so it must stay the same for the same list.
    cohort_description: str
    # Names the list in a note, such as 'the Resend segment "VIPs"'.
    source: str
    rows: tuple[dict[str, str], ...]
    # Said instead when the list has no contacts to import.
    empty_note: str = "No contacts to import."


def new_people_step(provider_label: str) -> ImportStepSpec:
    return ImportStepSpec(
        key=NEW_PEOPLE_STEP,
        label="New people from contacts",
        description=(
            f"Creates a person for each {provider_label} contact whose email matches no one in PostHog, with the "
            "email as their ID. Needs Contacts selected too. Each new person counts as one event. If your app "
            "identifies people by another ID, it should also set their email, or PostHog keeps two people for them."
        ),
    )


class ContactCollector:
    """Keeps each contact once, by email, so a contact on several lists is one row that every list shares.

    A repeat adds the properties the first entry lacked. The total stops at MAX_CONTACT_MEMBERSHIPS and
    MAX_CONTACT_BYTES, so one large account can't fill the worker's memory.
    """

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, str]] = {}
        self._memberships = 0
        self._bytes = 0

    def add(self, email: Any, properties: Mapping[str, Any]) -> dict[str, str] | None:
        address = exact_email(email)
        if address is None:
            return None
        self._memberships += 1
        if self._memberships > MAX_CONTACT_MEMBERSHIPS:
            raise ImportStepError(TOO_MANY_CONTACTS_MESSAGE)
        row = self._rows.get(address.lower())
        if row is None:
            row = self._rows[address.lower()] = {"email": address}
            self._bytes += _row_bytes(row)
        self._bytes += _add_properties(row, properties)
        if self._bytes > MAX_CONTACT_BYTES:
            raise ImportStepError(TOO_MANY_CONTACTS_MESSAGE)
        return row

    @property
    def everyone(self) -> tuple[dict[str, str], ...]:
        return tuple(self._rows.values())


def _add_properties(row: dict[str, str], properties: Mapping[str, Any]) -> int:
    """Adds the properties the row lacks while it stays within the people import's row limit, and returns the bytes
    added."""
    size = _row_bytes(row)
    added = 0
    for key, value in properties.items():
        name = str(key).strip()
        text = _property_text(value)
        if (
            not text
            or name in row
            or len(name) > MAX_PROPERTY_NAME_LENGTH
            or name.startswith("$")
            or _loose_name(name) in _IDENTITY_NAMES
        ):
            continue
        cost = _field_bytes(name, text)
        if size + cost > MAX_PEOPLE_IMPORT_ROW_BYTES:
            continue
        row[name] = text
        size += cost
        added += cost
    return added


def _row_bytes(row: Mapping[str, str]) -> int:
    return sum(_field_bytes(name, value) for name, value in row.items())


def _field_bytes(name: str, value: str) -> int:
    # The quotes, colon, comma and space a field adds when the people import writes the row as JSON.
    return len(name.encode()) + len(value.encode()) + 6


def save_contact_lists(context: ImportContext, everyone: ContactList, lists: Iterable[ContactList]) -> SavedPage:
    """Import `everyone` as people, then fill a cohort for each of `lists`, whose contacts are all in `everyone`.

    Only `everyone` sends the events that create and update people, so a contact in several lists counts once.
    """
    create_people = NEW_PEOPLE_STEP in context.steps
    result = _import(context, everyone, create_people=create_people, send_events=True)
    notes = _notes(everyone, result)
    if result.people:
        notes.append(
            f"{_contacts(result.people)} sent, {result.new_people:,} of them new people. They join this cohort and "
            "the ones below once PostHog has processed them, usually within a few minutes."
        )
    if result.skipped_new_people:
        notes.append(
            f"{_match_no_one(result.skipped_new_people)}, so no cohort has them. Import again "
            "with New people from contacts selected to add them."
        )
    items = [_item(everyone, result, tuple(notes))]
    for contact_list in lists:
        # A list waits on people the import above creates, so it can't have people that import left out.
        list_result = _import(context, contact_list, create_people=create_people, send_events=False)
        list_notes = _notes(contact_list, list_result)
        if list_result.people:
            list_notes.append(f"{_contacts(list_result.people)}.")
        if list_result.skipped_new_people:
            list_notes.append(f"{_match_no_one(list_result.skipped_new_people)}, so they aren't here.")
        items.append(_item(contact_list, list_result, tuple(list_notes)))
    return SavedPage(
        imported=result.people,
        counts={
            "people": result.people,
            "new_people": result.new_people,
            "skipped_new_people": result.skipped_new_people,
            "dropped": result.dropped,
        },
        items=tuple(items),
    )


def _import(
    context: ImportContext, contact_list: ContactList, *, create_people: bool, send_events: bool
) -> ProviderContactsResult:
    return import_provider_contacts(
        context.team_id,
        context.created_by_id,
        contact_list.rows,
        create_people=create_people,
        send_events=send_events,
        cohort_name=contact_list.cohort_name,
        cohort_description=contact_list.cohort_description,
        source=contact_list.source,
    )


def _notes(contact_list: ContactList, result: ProviderContactsResult) -> list[str]:
    return [contact_list.empty_note] if not contact_list.rows else list(result.notes)


def _contacts(count: int) -> str:
    return f"{count:,} contact" if count == 1 else f"{count:,} contacts"


def _match_no_one(count: int) -> str:
    return f"{_contacts(count)} {'matches' if count == 1 else 'match'} no one in PostHog"


def _item(contact_list: ContactList, result: ProviderContactsResult, notes: tuple[str, ...]) -> ImportItem:
    return ImportItem(
        label=result.cohort_name or contact_list.cohort_name,
        status=result.status,
        url=f"/cohorts/{result.cohort_id}" if result.cohort_id else None,
        notes=notes,
    )


def new_people_page() -> SavedPage:
    """The new people step has nothing of its own to save: it changes what the contacts step does."""
    return SavedPage(imported=0)


def _property_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        text = str(value).strip()
        return text if len(text) <= MAX_PROPERTY_VALUE_LENGTH else ""
    return ""


def _loose_name(name: str) -> str:
    return _NAME_SEPARATORS.sub("_", name.lower()).strip("_")
