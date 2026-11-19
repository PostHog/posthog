"""Uploaded people lists: each row creates or updates a person, and the people form a static cohort."""

import re
import json
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, NotRequired, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from structlog import get_logger

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.person.util import (
    get_distinct_ids_for_persons,
    get_person_ids_and_uuids_by_uuids,
    get_person_uuids_and_matched_distinct_ids,
)
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage import object_storage

from products.access_control.backend.property_access_control import get_non_writable_property_names
from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models import PropertyDefinition
from products.workflows.backend.facade.contracts import PeopleImportInvalid, PeopleImportSummary
from products.workflows.backend.models.people_import_batch import PeopleImportBatch

logger = get_logger(__name__)

MAX_PEOPLE_IMPORT_ROWS = 50_000
# Person properties are stored per person, so one row must not grow a profile without bound.
MAX_PEOPLE_IMPORT_ROW_BYTES = 4096
# Bounds each HogQL email lookup, so a full file takes five queries.
EMAIL_LOOKUP_CHUNK_SIZE = 10_000
# Bounds each personhog lookup of distinct IDs.
PERSON_LOOKUP_CHUNK_SIZE = 1000

# An import finishes in under 30 minutes, including the waits for ingestion and the capture retries.
STALLED_IMPORT_AFTER = timedelta(hours=1)
# The stall check repeats this often while a dispatch is retried or the cohort population is still running.
MAX_STALL_CHECKS = 6
# A batch fill claimed this long ago without starting was lost, so another task may claim it.
FILL_CLAIM_EXPIRES = timedelta(hours=1)
# A population that hasn't started by then was lost on its way to a worker.
POPULATION_START_TIMEOUT = timedelta(hours=1)

# Capture rejects longer distinct IDs (CAPTURE_V1_DISTINCT_ID_MAX_SIZE in rust/capture).
MAX_DISTINCT_ID_BYTES = 200
# Capture turns off person processing for these (ILLEGAL_DISTINCT_IDS in rust/capture), so no person would exist.
ILLEGAL_DISTINCT_IDS = frozenset(
    {
        "0",
        "00000000-0000-0000-0000-000000000000",
        "[object object]",
        "anonymous",
        "anonymous-user",
        "backend",
        "distinct_id",
        "distinctid",
        "email",
        "false",
        "guest",
        "id",
        "nan",
        "none",
        "not_authenticated",
        "null",
        "system",
        "true",
        "undefined",
        "user",
    }
)
# Only these headers are matched loosely. Every other header is a person property name, kept as written.
_IDENTITY_HEADERS = ("email", "distinct_id")
# Customer.io exports name the person's ID "id", so it names the distinct ID when the file has no distinct_id column.
_ID_HEADER = "id"

_STORAGE_FOLDER = "workflows_people_imports"
_HEADER_SEPARATORS = re.compile(r"[^a-z0-9]+")


class StagedPerson(TypedDict):
    """One person as the import stores it for the capture task."""

    distinct_id: str
    properties: dict[str, str]
    # Only fills properties the person doesn't have yet.
    fill_only: NotRequired[bool]


@frozen
class _CleanedRows:
    rows: list[dict[str, str]]
    columns: list[str]
    dropped_invalid_email: int
    dropped_duplicate_email: int
    dropped_too_large: int


def start_people_import(
    *,
    team: Team,
    user: User | None,
    name: str,
    rows: list[dict[str, str]],
    cohort_id: int | None = None,
    create_missing: bool = True,
    send_events: bool = True,
    fill_only: bool = False,
    batch: tuple[UUID, int] | None = None,
    fill_cohort: bool = True,
) -> PeopleImportSummary:
    """Create or update a person per row, then add them to a new static cohort called `name`, or to `cohort_id`.

    Without `create_missing`, a row no person matches is left out instead of becoming a new person. Without
    `send_events`, the import only fills the cohort: another import of the same rows creates and updates the people.
    With `fill_only`, a person keeps the values they have, and the import sets only the properties they lack.
    `batch` names the batch from `start_people_import_batch` and this import's part of it. Without `fill_cohort`, the
    import only sends the events and leaves `cohort_id` as it is, for people another import adds to the cohort.
    """
    if cohort_id is None and not create_missing:
        raise ValueError("An import that leaves out new people adds the rest to an existing cohort.")
    if len(rows) > MAX_PEOPLE_IMPORT_ROWS:
        raise PeopleImportInvalid(
            f"This file has {len(rows):,} rows. A file can have up to {MAX_PEOPLE_IMPORT_ROWS:,}."
        )

    cleaned = _clean_rows(rows)
    if not cleaned.rows and batch is None:
        raise PeopleImportInvalid("No row has a valid email address.")
    _check_writable_columns(team, user, cleaned.columns)

    resolved_people = _resolve_distinct_ids(team, user, cleaned.rows)
    distinct_ids = resolved_people.distinct_ids
    person_emails = tuple(sorted({spelling for spelled in resolved_people.spellings.values() for spelling in spelled}))
    people: list[StagedPerson] = []
    seen_distinct_ids: set[str] = set()
    dropped_duplicate_distinct_id = 0
    skipped_new_people = 0
    for row, distinct_id in zip(cleaned.rows, distinct_ids):
        if distinct_id is None and not create_missing:
            skipped_new_people += 1
            continue
        # A row with no person yet becomes one, keyed by the CSV's distinct_id or else its email.
        resolved = distinct_id or row["email"]
        if resolved in seen_distinct_ids:
            dropped_duplicate_distinct_id += 1
            continue
        seen_distinct_ids.add(resolved)
        people.append(
            {"distinct_id": resolved, "properties": row, "fill_only": True}
            if fill_only
            else {"distinct_id": resolved, "properties": row}
        )

    if not people:
        # Every row was left out, so there is nothing to send and the cohort stays as it is.
        assert cohort_id is not None
        if batch is not None:
            _on_part_ready(team.id, *batch, storage_key=None)
        return PeopleImportSummary(
            cohort_id=cohort_id,
            row_count=0,
            new_people=0,
            columns=cleaned.columns,
            dropped_invalid_email=cleaned.dropped_invalid_email,
            dropped_duplicate_email=cleaned.dropped_duplicate_email,
            dropped_too_large=cleaned.dropped_too_large,
            skipped_new_people=skipped_new_people,
            person_emails=person_emails,
        )
    existing = existing_distinct_ids(team.id, [person["distinct_id"] for person in people])
    if fill_cohort:
        target_id = _start_filling(team, user, name, cohort_id)
    else:
        assert cohort_id is not None and send_events
        target_id = cohort_id
    storage_key = f"{_STORAGE_FOLDER}/team-{team.id}/{target_id}-{uuid.uuid4()}.json"

    # The task module imports this one, so a module-level import would be circular.
    from products.workflows.backend.tasks.people_import import fail_people_import_if_stalled  # noqa: PLC0415

    try:
        object_storage.write(storage_key, json.dumps(people))
        # A row written in the caller's transaction shows the import committed. A batch's own row does that for a part.
        marker = start_people_import_batch(team.id, target_id, 1) if batch is None else None
        _set_phase(
            storage_key,
            ImportPhase.STAGED,
            send_events=send_events,
            batch=batch,
            fill_cohort=fill_cohort,
            commit_marker=marker,
        )
        # Scheduled before the caller commits, so the stored rows are deleted even when its transaction rolls back,
        # and the import is dispatched again when the dispatch below fails or never runs.
        fail_people_import_if_stalled.apply_async(
            kwargs={"team_id": team.id, "cohort_id": target_id, "storage_key": storage_key},
            countdown=int(STALLED_IMPORT_AFTER.total_seconds()),
        )
    except Exception:
        fail_people_import(team.id, target_id, storage_key, fills_cohort=fill_cohort)
        raise

    # A caller's transaction can still roll back the cohort, and events sent before that can't be taken back.
    # `robust` keeps one failed dispatch from skipping the other imports the same transaction started.
    transaction.on_commit(
        lambda: dispatch_people_import(team.id, target_id, storage_key, send_events=send_events), robust=True
    )

    return PeopleImportSummary(
        cohort_id=target_id,
        row_count=len(people),
        new_people=sum(1 for person in people if person["distinct_id"] not in existing),
        columns=cleaned.columns,
        dropped_invalid_email=cleaned.dropped_invalid_email,
        dropped_duplicate_email=cleaned.dropped_duplicate_email + dropped_duplicate_distinct_id,
        dropped_too_large=cleaned.dropped_too_large,
        skipped_new_people=skipped_new_people,
        person_emails=person_emails,
    )


def _start_filling(team: Team, user: User | None, name: str, cohort_id: int | None) -> int:
    """The cohort the import fills, marked as calculating until the import adds its people."""
    if cohort_id is None:
        return Cohort.objects.create(
            team_id=team.id, name=name, is_static=True, is_calculating=True, created_by=user
        ).pk
    if not Cohort.objects.filter(team_id=team.id, pk=cohort_id, is_static=True, deleted=False).update(
        is_calculating=True
    ):
        raise PeopleImportInvalid("The cohort for this import was deleted or isn't static anymore.")
    return cohort_id


def read_people(storage_key: str) -> list[StagedPerson]:
    content = object_storage.read(storage_key, missing_ok=True)
    return json.loads(content) if content else []


def start_people_import_batch(team_id: int, cohort_id: int, parts: int) -> UUID:
    """Starts a batch of `parts` imports that fill one cohort together, once every part's people exist."""
    return PeopleImportBatch.objects.for_team(team_id).create(team_id=team_id, cohort_id=cohort_id, parts=parts).id


def claim_people_import_batch_fill(team_id: int, batch_id: UUID) -> bool:
    """Only one caller starts a batch's fill. Another can only after the claim expired with the fill not started."""
    now = timezone.now()
    return bool(
        PeopleImportBatch.objects.for_team(team_id)
        .filter(id=batch_id, failed=False)
        .filter(Q(fill_claimed_at__isnull=True) | Q(fill_claimed_at__lt=now - FILL_CLAIM_EXPIRES))
        .update(fill_claimed_at=now)
    )


def mark_people_import_part_ready(team_id: int, batch_id: UUID, part: int, storage_key: str | None) -> bool:
    """Records that a part's people exist. Only the call that completes the batch returns True, so the cohort fills
    once. A part recorded twice counts once."""
    with transaction.atomic():
        batch = PeopleImportBatch.objects.for_team(team_id).select_for_update().filter(id=batch_id).first()
        if batch is None or batch.failed or str(part) in batch.ready_parts:
            return False
        batch.ready_parts[str(part)] = storage_key
        batch.save(update_fields=["ready_parts"])
        return len(batch.ready_parts) == batch.parts


def people_import_batch_rows(team_id: int, batch_id: UUID) -> tuple[int, list[str]] | None:
    """The cohort a completed batch fills and the stored rows of its parts, or None for a batch that failed."""
    batch = PeopleImportBatch.objects.for_team(team_id).filter(id=batch_id, failed=False).first()
    if batch is None:
        return None
    return batch.cohort_id, [key for _, key in sorted(batch.ready_parts.items(), key=lambda item: int(item[0])) if key]


def fail_people_import_batch(team_id: int, batch_id: UUID) -> None:
    """Stops a batch whose part can't finish, so its other parts end instead of waiting for it."""
    PeopleImportBatch.objects.for_team(team_id).filter(id=batch_id).update(failed=True)


def finish_people_import_batch(team_id: int, batch_id: UUID) -> None:
    PeopleImportBatch.objects.for_team(team_id).filter(id=batch_id).delete()


def _on_part_ready(team_id: int, batch_id: UUID, part: int, *, storage_key: str | None) -> None:
    if not mark_people_import_part_ready(team_id, batch_id, part, storage_key):
        return
    if not claim_people_import_batch_fill(team_id, batch_id):
        return
    from products.workflows.backend.tasks.people_import import fill_people_import_batch  # noqa: PLC0415

    transaction.on_commit(lambda: fill_people_import_batch.delay(team_id=team_id, batch_id=str(batch_id)), robust=True)


def delete_people(storage_key: str) -> None:
    object_storage.delete(storage_key)
    object_storage.delete(_phase_key(storage_key))


def dispatch_people_import(team_id: int, cohort_id: int, storage_key: str, *, send_events: bool) -> None:
    """Start the tasks that send the stored rows and fill the cohort. A failed dispatch is kept for the stall check."""
    from products.workflows.backend.tasks.people_import import (  # noqa: PLC0415
        capture_people_import,
        schedule_people_import_fill,
    )

    try:
        _set_phase(storage_key, ImportPhase.DISPATCHED, send_events=send_events)
        if send_events:
            capture_people_import.delay(team_id=team_id, cohort_id=cohort_id, storage_key=storage_key)
        else:
            schedule_people_import_fill(team_id=team_id, cohort_id=cohort_id, storage_key=storage_key)
    except Exception:
        logger.exception("people_import_dispatch_failed", team_id=team_id, cohort_id=cohort_id)
        try:
            _set_phase(storage_key, ImportPhase.DISPATCH_FAILED, send_events=send_events)
        except Exception:
            fail_people_import(team_id, cohort_id, storage_key)


def mark_people_import_populating(storage_key: str) -> None:
    """Records that the cohort population started, so the stall check follows it until it ends."""
    _set_phase(storage_key, ImportPhase.POPULATING)


def people_import_fills_cohort(storage_key: str) -> bool:
    """Whether the import adds its people to its cohort, or only sends their events."""
    return bool(_read_phase(storage_key).get("fill_cohort", True))


def people_import_part(storage_key: str) -> tuple[UUID, int] | None:
    """The batch and part an import belongs to, or None for an import that fills its cohort alone."""
    batch = _read_phase(storage_key).get("batch")
    return (UUID(batch[0]), int(batch[1])) if batch else None


def wait_for_other_parts(team_id: int, storage_key: str) -> bool:
    """Records that this part's people exist. True when it was the last part, so its caller fills the cohort."""
    part = people_import_part(storage_key)
    assert part is not None
    _set_phase(storage_key, ImportPhase.WAITING_FOR_PARTS)
    return mark_people_import_part_ready(team_id, *part, storage_key) and claim_people_import_batch_fill(
        team_id, part[0]
    )


def finish_people_import_rows(team_id: int, storage_key: str) -> None:
    """Deletes what a finished import stored."""
    _drop_commit_marker(team_id, _read_phase(storage_key))
    delete_people(storage_key)


def _drop_commit_marker(team_id: int, state: dict[str, Any]) -> None:
    if state.get("commit_marker"):
        finish_people_import_batch(team_id, UUID(state["commit_marker"]))


def _committed(team_id: int, state: dict[str, Any]) -> bool:
    """Whether the caller that staged the import committed, from the row it wrote in the same transaction."""
    marker = state.get("commit_marker") or (state.get("batch") or [None])[0]
    return bool(marker) and PeopleImportBatch.objects.for_team(team_id).filter(id=marker).exists()


def fail_people_import(team_id: int, cohort_id: int, storage_key: str, *, fills_cohort: bool | None = None) -> None:
    """Ends an import that can't finish: the cohort stops calculating and shows an error.

    `fills_cohort` says whether the import owns the cohort, for a caller that knows. Otherwise the import's record
    says, and an import without one leaves the cohort alone.
    """
    state: dict[str, Any] = {}
    try:
        state = _read_phase(storage_key)
        _drop_commit_marker(team_id, state)
        batch = state.get("batch")
        if batch:
            fail_people_import_batch(team_id, UUID(batch[0]))
    except Exception:
        logger.exception("people_import_batch_fail_failed", team_id=team_id, cohort_id=cohort_id)
    if fills_cohort is None:
        fills_cohort = bool(state) and bool(state.get("fill_cohort", True))
    if fills_cohort:
        Cohort.objects.filter(pk=cohort_id, team_id=team_id).update(
            is_calculating=False, errors_calculating=F("errors_calculating") + 1, last_error_at=timezone.now()
        )
    try:
        delete_people(storage_key)
    except Exception:
        logger.exception("people_import_cleanup_failed", team_id=team_id, cohort_id=cohort_id)


class StallCheck(StrEnum):
    FINISHED = "finished"
    FAILED = "failed"
    WAITING = "waiting"


def check_stalled_people_import(team_id: int, cohort_id: int, storage_key: str, *, check: int) -> StallCheck:
    """Ends, dispatches again, or keeps waiting on an import that hasn't deleted its rows yet.

    `check` counts the earlier checks of the import. WAITING asks the caller to check again later.
    """
    # A finished import deletes its rows. Checking them, not the cohort, leaves a later import of the cohort alone.
    if object_storage.read(storage_key, missing_ok=True) is None:
        return StallCheck.FINISHED
    state = _read_phase(storage_key)
    if not state:
        # Staging stopped before it recorded the import, so nothing will send these rows.
        delete_people(storage_key)
        return StallCheck.FINISHED
    phase = state.get("phase")
    cohort = Cohort.objects.filter(pk=cohort_id, team_id=team_id).first()
    last_check = check + 1 >= MAX_STALL_CHECKS
    if phase == ImportPhase.STAGED and not _committed(team_id, state):
        # A caller staging a long list can still be in its transaction, so only the last check takes it as rolled back.
        if not last_check:
            return StallCheck.WAITING
        delete_people(storage_key)
        return StallCheck.FINISHED
    if phase in (ImportPhase.STAGED, ImportPhase.DISPATCH_FAILED) and not last_check:
        # The caller committed, but the dispatch failed or never ran.
        dispatch_people_import(team_id, cohort_id, storage_key, send_events=bool(state.get("send_events", True)))
        return StallCheck.WAITING
    if phase == ImportPhase.WAITING_FOR_PARTS and not last_check:
        batch = PeopleImportBatch.objects.for_team(team_id).filter(id=state["batch"][0]).first()
        if batch is not None and not batch.failed:
            if len(batch.ready_parts) == batch.parts and claim_people_import_batch_fill(team_id, batch.id):
                # Every part is in but the cohort fill never started, so the last part's dispatch was lost.
                from products.workflows.backend.tasks.people_import import fill_people_import_batch  # noqa: PLC0415

                fill_people_import_batch.delay(team_id=team_id, batch_id=str(batch.id))
            return StallCheck.WAITING
    if phase == ImportPhase.POPULATING and cohort is not None:
        if not cohort.is_calculating:
            # The population ended, and the cohort shows how. Only the cleanup after it went missing.
            finish_people_import_rows(team_id, storage_key)
            return StallCheck.FINISHED
        started = datetime.fromisoformat(state["at"])
        attempts = CohortCalculationHistory.objects.filter(cohort_id=cohort_id, started_at__gte=started)
        lost = not attempts.exists() and timezone.now() - started > POPULATION_START_TIMEOUT
        if not lost and not last_check:
            return StallCheck.WAITING
    fail_people_import(team_id, cohort_id, storage_key)
    return StallCheck.FAILED


class ImportPhase(StrEnum):
    STAGED = "staged"
    DISPATCHED = "dispatched"
    DISPATCH_FAILED = "dispatch_failed"
    WAITING_FOR_PARTS = "waiting_for_parts"
    POPULATING = "populating"


def _phase_key(storage_key: str) -> str:
    return f"{storage_key.removesuffix('.json')}.phase.json"


def _set_phase(
    storage_key: str,
    phase: ImportPhase,
    *,
    send_events: bool | None = None,
    batch: tuple[UUID, int] | None = None,
    fill_cohort: bool | None = None,
    commit_marker: UUID | None = None,
) -> None:
    state: dict[str, object] = {**_read_phase(storage_key), "phase": phase.value, "at": timezone.now().isoformat()}
    if send_events is not None:
        state["send_events"] = send_events
    if batch is not None:
        state["batch"] = [str(batch[0]), batch[1]]
    if fill_cohort is not None:
        state["fill_cohort"] = fill_cohort
    if commit_marker is not None:
        state["commit_marker"] = str(commit_marker)
    object_storage.write(_phase_key(storage_key), json.dumps(state))


def _read_phase(storage_key: str) -> dict[str, Any]:
    content = object_storage.read(_phase_key(storage_key), missing_ok=True)
    return json.loads(content) if content else {}


def existing_distinct_ids(team_id: int, distinct_ids: list[str]) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(distinct_ids), PERSON_LOOKUP_CHUNK_SIZE):
        _, matched = get_person_uuids_and_matched_distinct_ids(
            team_id, distinct_ids[start : start + PERSON_LOOKUP_CHUNK_SIZE]
        )
        found.update(matched)
    return found


def _clean_rows(rows: list[dict[str, str]]) -> _CleanedRows:
    id_names_distinct_id = "distinct_id" not in {_loose_header(header) for raw in rows for header in raw}
    kept: list[dict[str, str]] = []
    columns: dict[str, None] = {}
    seen_emails: set[str] = set()
    has_email_column = False
    dropped_invalid_email = dropped_duplicate_email = dropped_too_large = 0
    for line, raw in enumerate(rows, start=2):
        row: dict[str, str] = {}
        row_keys: set[str] = set()
        for header, value in raw.items():
            key = _column_key(header, id_names_distinct_id)
            if not key:
                # Skipping a column that holds data would lose that data without saying so.
                if str(value).strip():
                    raise PeopleImportInvalid("A column with data in it has no name. Name it and try again.")
                continue
            if key in row_keys:
                # Keeping either value would set the wrong property without saying so.
                raise PeopleImportInvalid(f'Two columns are both named "{key}". Rename one and try again.')
            row_keys.add(key)
            cell = str(value).strip()
            # A blank cell would $set "" and wipe the value the person already has.
            if cell:
                row[key] = cell
        has_email_column = has_email_column or "email" in row_keys
        _check_distinct_id(row.get("distinct_id", ""), line)
        email = row.get("email", "")
        try:
            validate_email(email)
        except DjangoValidationError:
            dropped_invalid_email += 1
            continue
        if not row.get("distinct_id") and len(email.encode()) > MAX_DISTINCT_ID_BYTES:
            # A row without a distinct_id may become a person keyed by its email, which capture would refuse.
            dropped_invalid_email += 1
            continue
        if email.lower() in seen_emails:
            dropped_duplicate_email += 1
            continue
        if len(json.dumps(row).encode()) > MAX_PEOPLE_IMPORT_ROW_BYTES:
            dropped_too_large += 1
            continue
        seen_emails.add(email.lower())
        columns.update(dict.fromkeys(key for key in row if key != "distinct_id"))
        kept.append(row)
    if not has_email_column:
        raise PeopleImportInvalid('Add a column named "email" with each person\'s address.')
    return _CleanedRows(
        rows=kept,
        columns=list(columns),
        dropped_invalid_email=dropped_invalid_email,
        dropped_duplicate_email=dropped_duplicate_email,
        dropped_too_large=dropped_too_large,
    )


def _check_distinct_id(distinct_id: str, line: int) -> None:
    if not distinct_id:
        return
    if len(distinct_id.encode()) > MAX_DISTINCT_ID_BYTES:
        raise PeopleImportInvalid(
            f"The distinct_id on row {line} is longer than {MAX_DISTINCT_ID_BYTES} bytes. Shorten it and try again."
        )
    if distinct_id.lower() in ILLEGAL_DISTINCT_IDS:
        raise PeopleImportInvalid(
            f'Row {line} has the distinct_id "{distinct_id}", which PostHog can\'t use for a person. '
            "Use the person's ID from your app, or leave it empty to match by email."
        )


def _check_writable_columns(team: Team, user: User | None, columns: list[str]) -> None:
    non_writable = get_non_writable_property_names(
        team_id=team.id, user=user, property_type=PropertyDefinition.Type.PERSON
    )
    blocked = sorted(set(columns) & non_writable)
    if blocked:
        raise PeopleImportInvalid(
            f"You can't change these person properties: {', '.join(blocked)}. Remove those columns and try again."
        )


@frozen
class _ResolvedPeople:
    # The distinct ID each row writes to, or None for a row no person matches.
    distinct_ids: list[str | None]
    # How the people that rows matched by email spell that email, by lowercased email.
    spellings: dict[str, tuple[str, ...]]


def _resolve_distinct_ids(team: Team, user: User | None, rows: list[dict[str, str]]) -> _ResolvedPeople:
    """The distinct ID each row writes to: its own column first, then an existing person with the email."""
    emails = [row["email"].lower() for row in rows if not row.get("distinct_id")]
    by_email: dict[str, str] = {}
    spellings: dict[str, tuple[str, ...]] = {}
    for start in range(0, len(emails), EMAIL_LOOKUP_CHUNK_SIZE):
        matched = _distinct_ids_by_email(team, user, emails[start : start + EMAIL_LOOKUP_CHUNK_SIZE])
        by_email.update(matched.distinct_ids)
        spellings.update(matched.spellings)
    resolved: list[str | None] = []
    for row in rows:
        distinct_id = row.pop("distinct_id", "")
        resolved.append(distinct_id or by_email.get(row["email"].lower()))
    return _ResolvedPeople(distinct_ids=resolved, spellings=spellings)


@frozen
class _MatchedEmails:
    distinct_ids: dict[str, str]
    spellings: dict[str, tuple[str, ...]]


def _distinct_ids_by_email(team: Team, user: User | None, emails: list[str]) -> _MatchedEmails:
    if not emails:
        return _MatchedEmails(distinct_ids={}, spellings={})
    # Querying persons directly lets HogQL filter people by email before it groups their versions.
    # The lowest person ID per email is the same person the email dedupe of a filtered audience picks.
    query = parse_select(
        """
        SELECT
            lower(trim(toString(properties.email))) AS normalized_email,
            min(id) AS person_uuid,
            groupUniqArray(trim(toString(properties.email))) AS spellings
        FROM persons
        WHERE lower(trim(toString(properties.email))) IN {emails}
        GROUP BY normalized_email
        LIMIT {limit}
        """,
        # Without a limit HogQL returns 100 rows, which is fewer than one chunk of emails.
        placeholders={"emails": ast.Constant(value=emails), "limit": ast.Constant(value=len(emails))},
    )
    tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
    # With the user, property access rules that hide email from the team default still let this user match.
    response = execute_hogql_query(query=query, team=team, user=user, workload=Workload.OFFLINE)
    uuid_by_email = {email: uuid.UUID(str(person_uuid)) for email, person_uuid, _ in response.results}
    spellings = {email: tuple(sorted(spelled)) for email, _, spelled in response.results}
    id_by_uuid = {
        uuid.UUID(str(person_uuid)): person_id
        for person_id, person_uuid in get_person_ids_and_uuids_by_uuids(
            team.id, [str(person_uuid) for person_uuid in set(uuid_by_email.values())]
        )
    }
    # Any of the person's distinct IDs will do: the row writes its properties to the person behind it.
    distinct_ids = get_distinct_ids_for_persons(team.id, list(id_by_uuid.values()), limit_per_person=1)
    matched: dict[str, str] = {}
    for email, person_uuid in uuid_by_email.items():
        person_id = id_by_uuid.get(person_uuid)
        if person_id is not None and distinct_ids.get(person_id):
            matched[email] = distinct_ids[person_id][0]
    return _MatchedEmails(
        distinct_ids=matched, spellings={email: spellings[email] for email in matched if email in spellings}
    )


def _loose_header(header: object) -> str:
    return _HEADER_SEPARATORS.sub("_", str(header).strip().lower()).strip("_")


def _column_key(header: object, id_names_distinct_id: bool) -> str:
    """The identity column a header names, or else the header itself as the person property name."""
    loose = _loose_header(header)
    if loose in _IDENTITY_HEADERS:
        return loose
    if loose == _ID_HEADER and id_names_distinct_id:
        return "distinct_id"
    return str(header).strip()
