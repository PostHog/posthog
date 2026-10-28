"""Uploaded people lists: each row creates or updates a person, and the people form a static cohort."""

import re
import json
import uuid
from datetime import timedelta
from typing import TypedDict

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db.models import F
from django.utils import timezone

from structlog import get_logger

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import PropertyDefinition
from posthog.models.person.util import (
    get_distinct_ids_for_persons,
    get_person_ids_and_uuids_by_uuids,
    get_person_uuids_and_matched_distinct_ids,
)
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage import object_storage

from products.access_control.backend.property_access_control import get_non_writable_property_names
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import PeopleImportInvalid, PeopleImportSummary

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


@frozen
class _CleanedRows:
    rows: list[dict[str, str]]
    columns: list[str]
    dropped_invalid_email: int
    dropped_duplicate_email: int
    dropped_too_large: int


def start_people_import(*, team: Team, user: User | None, name: str, rows: list[dict[str, str]]) -> PeopleImportSummary:
    if len(rows) > MAX_PEOPLE_IMPORT_ROWS:
        raise PeopleImportInvalid(
            f"This file has {len(rows):,} rows. A file can have up to {MAX_PEOPLE_IMPORT_ROWS:,}."
        )

    cleaned = _clean_rows(rows)
    if not cleaned.rows:
        raise PeopleImportInvalid("No row has a valid email address.")
    _check_writable_columns(team, user, cleaned.columns)

    distinct_ids = _resolve_distinct_ids(team, user, cleaned.rows)
    people: list[StagedPerson] = []
    seen_distinct_ids: set[str] = set()
    dropped_duplicate_distinct_id = 0
    for row, distinct_id in zip(cleaned.rows, distinct_ids):
        # A row with no person yet becomes one, keyed by the CSV's distinct_id or else its email.
        resolved = distinct_id or row["email"]
        if resolved in seen_distinct_ids:
            dropped_duplicate_distinct_id += 1
            continue
        seen_distinct_ids.add(resolved)
        people.append({"distinct_id": resolved, "properties": row})

    existing = existing_distinct_ids(team.id, [person["distinct_id"] for person in people])
    cohort = Cohort.objects.create(team_id=team.id, name=name, is_static=True, is_calculating=True, created_by=user)
    storage_key = f"{_STORAGE_FOLDER}/team-{team.id}/{cohort.pk}-{uuid.uuid4()}.json"

    # The task module imports this one, so a module-level import would be circular.
    from products.workflows.backend.tasks.people_import import (  # noqa: PLC0415
        capture_people_import,
        fail_people_import_if_stalled,
    )

    try:
        object_storage.write(storage_key, json.dumps(people))
        capture_people_import.delay(team_id=team.id, cohort_id=cohort.pk, storage_key=storage_key)
        # A worker that dies mid-task, or a task that can't schedule the next one, leaves the cohort calculating.
        # The stuck-cohort sweep resets an uploaded cohort only after SOURCELESS_STATIC_COHORT_STUCK_AFTER. The sweep
        # does not delete the stored rows. This check ends the import sooner and deletes them.
        fail_people_import_if_stalled.apply_async(
            kwargs={"team_id": team.id, "cohort_id": cohort.pk, "storage_key": storage_key},
            countdown=int(STALLED_IMPORT_AFTER.total_seconds()),
        )
    except Exception:
        # No task would finish this cohort. The stuck-cohort sweep would leave it calculating until
        # SOURCELESS_STATIC_COHORT_STUCK_AFTER passes.
        fail_people_import(team.id, cohort.pk, storage_key)
        raise

    return PeopleImportSummary(
        cohort_id=cohort.pk,
        row_count=len(people),
        new_people=sum(1 for person in people if person["distinct_id"] not in existing),
        columns=cleaned.columns,
        dropped_invalid_email=cleaned.dropped_invalid_email,
        dropped_duplicate_email=cleaned.dropped_duplicate_email + dropped_duplicate_distinct_id,
        dropped_too_large=cleaned.dropped_too_large,
    )


def read_people(storage_key: str) -> list[StagedPerson]:
    content = object_storage.read(storage_key, missing_ok=True)
    return json.loads(content) if content else []


def delete_people(storage_key: str) -> None:
    object_storage.delete(storage_key)


def fail_people_import(team_id: int, cohort_id: int, storage_key: str) -> None:
    """Ends an import that can't finish: the cohort stops calculating and shows an error."""
    Cohort.objects.filter(pk=cohort_id, team_id=team_id).update(
        is_calculating=False, errors_calculating=F("errors_calculating") + 1, last_error_at=timezone.now()
    )
    try:
        delete_people(storage_key)
    except Exception:
        logger.exception("people_import_cleanup_failed", team_id=team_id, cohort_id=cohort_id)


def fail_stalled_people_import(team_id: int, cohort_id: int, storage_key: str) -> bool:
    if not Cohort.objects.filter(pk=cohort_id, team_id=team_id, is_calculating=True).exists():
        return False
    fail_people_import(team_id, cohort_id, storage_key)
    return True


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


def _resolve_distinct_ids(team: Team, user: User | None, rows: list[dict[str, str]]) -> list[str | None]:
    """The distinct ID each row writes to: its own column first, then an existing person with the email."""
    emails = [row["email"].lower() for row in rows if not row.get("distinct_id")]
    by_email: dict[str, str] = {}
    for start in range(0, len(emails), EMAIL_LOOKUP_CHUNK_SIZE):
        by_email.update(_distinct_ids_by_email(team, user, emails[start : start + EMAIL_LOOKUP_CHUNK_SIZE]))
    resolved: list[str | None] = []
    for row in rows:
        distinct_id = row.pop("distinct_id", "")
        resolved.append(distinct_id or by_email.get(row["email"].lower()))
    return resolved


def _distinct_ids_by_email(team: Team, user: User | None, emails: list[str]) -> dict[str, str]:
    if not emails:
        return {}
    # Querying persons directly lets HogQL filter people by email before it groups their versions.
    # The lowest person ID per email is the same person the email dedupe of a filtered audience picks.
    query = parse_select(
        """
        SELECT lower(trim(toString(properties.email))) AS normalized_email, min(id) AS person_uuid
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
    uuid_by_email = {email: uuid.UUID(str(person_uuid)) for email, person_uuid in response.results}
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
    return matched


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
