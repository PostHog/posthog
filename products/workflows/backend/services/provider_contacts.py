"""Turns a provider's contacts into people, matched by email, and keeps a static cohort to exactly the list.

A list is staged in parts in object storage while the import step saves. A Temporal workflow then sends each part,
waits for ingestion to create its people, and sets the cohort's members once every part is in.
"""

import json
import time
from collections.abc import Collection, Sequence

from structlog import get_logger

from posthog.api.capture import capture_batch_internal
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.storage import object_storage

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cohorts.backend.facade.api import (
    find_cohort_ref_by_description,
    get_cohort_ref,
    replace_static_cohort_members,
)
from products.workflows.backend.facade.contracts import (
    ContactChunkOutcome,
    ContactsCaptureFailed,
    ContactsCleanupFailed,
    ContactsCohortFilled,
    ContactsImportAccessLost,
    PeopleImportInvalid,
    ProviderContactsResult,
)
from products.workflows.backend.services.people_import import (
    MAX_PEOPLE_IMPORT_ROWS,
    StagedPerson,
    existing_distinct_ids,
    fail_cohort_fill,
    mark_cohort_filling,
    prepare_people,
    read_people,
    set_events,
)
from products.workflows.backend.services.provider_cohorts import import_cohort

logger = get_logger(__name__)

# People per part. Each part is one capture batch and one Temporal activity.
CONTACT_CHUNK_SIZE = 1000
EVENT_SOURCE = "workflows_provider_contacts"
CAPTURE_ATTEMPTS = 3
# Ingestion usually creates people within seconds. A part stops waiting after this, and the cohort reports the rest
# as unmatched.
WAIT_FOR_PEOPLE_SECONDS = 600
WAIT_FIRST_DELAY_SECONDS = 2
WAIT_MAX_DELAY_SECONDS = 30
_STORAGE_FOLDER = "workflows_provider_contacts"


def stage_provider_contacts(
    team_id: int,
    user_id: int | None,
    rows: Sequence[dict[str, str]],
    *,
    import_key: str,
    create_people: bool,
    send_events: bool,
    cohort_name: str,
    cohort_description: str,
    source: str,
    non_members: Collection[str] = (),
) -> ProviderContactsResult:
    """Find the person each contact's email matches, and store the list in parts for the import workflow to send.

    A person's existing values stay as they are, and a contact no person matches becomes a new person when
    `create_people` is set. Without `send_events`, the list only sets its cohort's members, and another list of the
    same contacts sends their events. `non_members` holds lowercased addresses whose people stay out of the cohort,
    such as contacts who unsubscribed. `import_key` names the import run and list, so a retried save overwrites its
    own parts. `source` names the list in a note, such as 'the Resend segment "VIPs"'.
    """
    # An empty list empties the cohort an earlier import filled, and makes no new one.
    if not rows and find_cohort_ref_by_description(team_id=team_id, description=cohort_description) is None:
        return ProviderContactsResult(status="skipped", notes=("No contacts to import.",))
    creator = _check_creator(team_id, user_id)
    if isinstance(creator, ProviderContactsResult):
        return creator
    team, user, access = creator.team, creator.user, creator.access
    cohort = import_cohort(team_id, user, access, description=cohort_description, name=cohort_name, source=source)
    if cohort.cohort_id is None:
        return ProviderContactsResult(status="failed", notes=(cohort.problem,))

    people: list[StagedPerson] = []
    seen: set[str] = set()
    skipped_new_people = dropped = 0
    person_emails: set[str] = set()
    try:
        # Each part of the lookup is bounded, so a long list doesn't hold one huge query.
        for start in range(0, len(rows), MAX_PEOPLE_IMPORT_ROWS):
            prepared = prepare_people(
                team,
                user,
                [dict(row) for row in rows[start : start + MAX_PEOPLE_IMPORT_ROWS]],
                create_missing=create_people,
                fill_only=True,
                require_rows=False,
            )
            skipped_new_people += prepared.skipped_new_people
            dropped += prepared.dropped_invalid_email + prepared.dropped_duplicate_email + prepared.dropped_too_large
            person_emails.update(prepared.person_emails)
            for person in prepared.people:
                if person["distinct_id"] in seen:
                    dropped += 1
                    continue
                seen.add(person["distinct_id"])
                if person["properties"]["email"].lower() in non_members:
                    person["member"] = False
                people.append(person)
        mark_cohort_filling(team_id, cohort.cohort_id)
    except PeopleImportInvalid as error:
        return ProviderContactsResult(
            status="failed", cohort_id=cohort.cohort_id, cohort_name=cohort.name, notes=(str(error),)
        )

    storage_prefix = f"{_STORAGE_FOLDER}/team-{team_id}/{import_key}"
    chunks = 0
    for chunks, start in enumerate(range(0, len(people), CONTACT_CHUNK_SIZE), start=1):
        object_storage.write(
            _chunk_key(storage_prefix, chunks - 1), json.dumps(people[start : start + CONTACT_CHUNK_SIZE])
        )
    existing = existing_distinct_ids(team_id, [person["distinct_id"] for person in people])
    return ProviderContactsResult(
        status="created" if people else "skipped",
        cohort_id=cohort.cohort_id,
        cohort_name=cohort.name,
        people=len(people),
        new_people=sum(1 for person in people if person["distinct_id"] not in existing),
        skipped_new_people=skipped_new_people,
        dropped=dropped,
        person_emails=tuple(sorted(person_emails)),
        storage_prefix=storage_prefix,
        chunks=chunks,
    )


def send_provider_contact_properties(
    team_id: int, user_id: int | None, rows: Sequence[dict[str, str]], *, import_key: str, create_people: bool
) -> ProviderContactsResult:
    """Fill in the properties each contact's person lacks, right away and without a cohort.

    A contact no person matches becomes a new person when `create_people` is set. The events can't be taken back
    when the caller's transaction rolls back, and sending them again on its retry sets the same values.
    """
    if not rows:
        return ProviderContactsResult(status="skipped")
    creator = _check_creator(team_id, user_id)
    if isinstance(creator, ProviderContactsResult):
        return creator
    team, user = creator.team, creator.user
    try:
        prepared = prepare_people(
            team, user, [dict(row) for row in rows], create_missing=create_people, fill_only=True, require_rows=False
        )
    except PeopleImportInvalid as error:
        return ProviderContactsResult(status="failed", notes=(str(error),))
    if prepared.people:
        _send(team, prepared.people, f"{_STORAGE_FOLDER}/team-{team_id}/{import_key}")
    return ProviderContactsResult(status="created" if prepared.people else "skipped", people=len(prepared.people))


@frozen
class _Creator:
    team: Team
    user: User
    access: UserAccessControl


def _require_creator(team_id: int, user_id: int | None) -> None:
    # The parts are written minutes or hours after the list was staged, so access is checked again for each.
    creator = _check_creator(team_id, user_id)
    if isinstance(creator, ProviderContactsResult):
        raise ContactsImportAccessLost(" ".join(creator.notes))


def _check_creator(team_id: int, user_id: int | None) -> _Creator | ProviderContactsResult:
    """The person who started the import, or a failed result when they can't edit persons in the project anymore."""
    team = Team.objects.get(id=team_id)
    user = User.objects.filter(id=user_id).first()
    if user is None:
        return ProviderContactsResult(status="failed", notes=("The person who started this import no longer exists.",))
    access = UserAccessControl(user=user, team=team)
    # The import runs in the background, so the person who started it may have lost access since.
    if not user.is_active or not access.has_project_access:
        return ProviderContactsResult(
            status="failed", notes=("The person who started this import can't access this project anymore.",)
        )
    if not access.check_access_level_for_resource("person", "editor"):
        return ProviderContactsResult(
            status="failed", notes=("The person who started this import can't edit persons in this project.",)
        )
    return _Creator(team=team, user=user, access=access)


def import_contact_chunk(
    team_id: int, storage_prefix: str, chunk: int, *, send_events: bool, created_by_id: int | None
) -> ContactChunkOutcome:
    """Send one stored part's events, then wait until ingestion has created its people.

    Running it again is safe: an event sets the same properties again, and people are keyed by distinct ID.
    """
    _require_creator(team_id, created_by_id)
    key = _chunk_key(storage_prefix, chunk)
    people = read_people(key)
    if send_events and people:
        _send(Team.objects.get(id=team_id), people, key)
    distinct_ids = [person["distinct_id"] for person in people]
    deadline = time.monotonic() + WAIT_FOR_PEOPLE_SECONDS
    delay = WAIT_FIRST_DELAY_SECONDS
    while True:
        found = existing_distinct_ids(team_id, distinct_ids)
        if len(found) >= len(distinct_ids) or time.monotonic() >= deadline:
            return ContactChunkOutcome(people=len(people), found=len(found))
        time.sleep(delay)
        delay = min(delay * 2, WAIT_MAX_DELAY_SECONDS)


def _send(team: Team, people: list[StagedPerson], key: str) -> None:
    # Capture ingests an acknowledged event again when it's resent, so what it acknowledged outlasts a retry.
    acknowledged_key = f"{key.removesuffix('.json')}.acknowledged.json"
    acknowledged = set(json.loads(object_storage.read(acknowledged_key, missing_ok=True) or "[]"))
    events = [event for event in set_events(people, key) if event["event_uuid"] not in acknowledged]
    for _ in range(CAPTURE_ATTEMPTS):
        if not events:
            return
        result = capture_batch_internal(
            events=events, token=team.api_token, event_source=EVENT_SOURCE, process_person_profile=True
        )
        # Capture can ack part of a batch, so the next try sends only the rest. A dropped event can't be delivered,
        # and the cohort reports its person as unmatched.
        unacknowledged = {*result.retried, *result.unaccounted}
        sent = {str(event["event_uuid"]) for event in events} - unacknowledged
        if sent and unacknowledged:
            acknowledged |= sent
            object_storage.write(acknowledged_key, json.dumps(sorted(acknowledged)))
        events = [event for event in events if event["event_uuid"] in unacknowledged]
    if events:
        raise ContactsCaptureFailed(f"Capture didn't acknowledge {len(events)} events.")


def fill_contacts_cohort(
    team_id: int, cohort_id: int, storage_prefix: str, chunks: int, *, created_by_id: int | None
) -> ContactsCohortFilled:
    """Set the cohort's members to the list's people, once every part is in. Anyone else in the cohort leaves it."""
    creator = _check_creator(team_id, created_by_id)
    if isinstance(creator, ProviderContactsResult):
        raise ContactsImportAccessLost(" ".join(creator.notes))
    cohort = get_cohort_ref(team_id=team_id, cohort_id=cohort_id)
    ref = (
        ObjectAccessRef(
            resource="cohort", id=str(cohort.id), team_id=cohort.team_id, created_by_id=cohort.created_by_id
        )
        if cohort is not None
        else None
    )
    # Replacing the members removes people too, so the creator must still be able to edit this cohort.
    if ref is None or not creator.access.check_access_level_for_ref(ref, "editor"):
        raise ContactsImportAccessLost("The person who started this import can't edit this cohort anymore.")
    members = [
        person["distinct_id"]
        for chunk in range(chunks)
        for person in read_people(_chunk_key(storage_prefix, chunk))
        if person.get("member", True)
    ]
    replaced = replace_static_cohort_members(team_id=team_id, cohort_id=cohort_id, distinct_ids=members)
    return ContactsCohortFilled(members=replaced.matched, removed=replaced.removed)


def fail_contacts_cohort(team_id: int, cohort_id: int) -> None:
    """The list couldn't finish, so its cohort stops calculating and shows an error."""
    fail_cohort_fill(team_id, cohort_id)


def discard_staged_contacts(team_id: int, import_key: str) -> None:
    """Delete every part an import stored, including those of a save that rolled back."""
    keys = list(object_storage.iter_keys(f"{_STORAGE_FOLDER}/team-{team_id}/{import_key}/"))
    failed: list[str] = []
    for start in range(0, len(keys), 1000):
        failed += object_storage.delete_objects(keys[start : start + 1000])
    if failed:
        raise ContactsCleanupFailed(f"{len(failed)} stored parts weren't deleted.")


def _chunk_key(storage_prefix: str, chunk: int) -> str:
    return f"{storage_prefix}/chunk-{chunk}.json"
