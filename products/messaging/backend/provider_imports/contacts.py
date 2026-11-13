"""Contact steps every provider import shares: each list of contacts becomes people and fills a cohort."""

from collections.abc import Iterable, Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.messaging.backend.provider_imports.base import ImportContext, ImportItem, ImportStepSpec, SavedPage
from products.messaging.backend.provider_imports.emails import exact_email
from products.workflows.backend.facade.contracts import ProviderContactsResult
from products.workflows.backend.facade.people_import import import_provider_contacts

NEW_PEOPLE_STEP = "new_people"
# Person properties hold short values, so a provider's longer custom field is left out rather than cut.
MAX_PROPERTY_VALUE_LENGTH = 1000

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


def contact_row(email: Any, properties: Mapping[str, Any]) -> dict[str, str] | None:
    """The person properties a contact sets, or None without a usable email address. Empty values are left out, so
    they don't wipe what PostHog already has."""
    address = exact_email(email)
    if address is None:
        return None
    row = {"email": address}
    for key, value in properties.items():
        text = _property_text(value)
        if key != "email" and text:
            row[key] = text
    return row


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
