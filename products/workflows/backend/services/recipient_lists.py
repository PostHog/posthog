"""Uploaded recipient lists: each row joins a static cohort, and its columns stay with the list for broadcast templates."""

import re
import json
from datetime import timedelta
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
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

from products.access_control.backend.property_access_control import get_non_writable_property_names
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import RecipientListColumns, RecipientListInvalid, RecipientListSummary
from products.workflows.backend.models.recipient_list import RecipientList, RecipientListRow

logger = get_logger(__name__)

MAX_RECIPIENT_LIST_ROWS = 50_000
# A soft-deleted cohort can be restored, so its list's rows are kept this long before they are deleted.
DELETED_COHORT_RETENTION = timedelta(days=7)
# An import finishes in under 30 minutes, including the waits for ingestion and the capture retries.
STALLED_IMPORT_AFTER = timedelta(hours=1)
# An hourly sweep looks back this far, so one missed run doesn't leave an import stuck.
STALLED_IMPORT_LOOKBACK = timedelta(days=2)
# Each row becomes the variables of one broadcast run, so one row must not grow a run's state without bound.
MAX_RECIPIENT_LIST_ROW_BYTES = 4096
# Bounds each HogQL email lookup, so a full file takes five queries.
EMAIL_LOOKUP_CHUNK_SIZE = 10_000
# Bounds each personhog lookup of distinct IDs.
PERSON_LOOKUP_CHUNK_SIZE = 1000
ROW_WRITE_BATCH_SIZE = 1000

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
# Only these headers are matched loosely. Every other header is a variable name, kept as written.
_IDENTITY_HEADERS = ("email", "distinct_id")
# Customer.io exports name the person's ID "id", so it names the distinct ID when the file has no distinct_id column.
_ID_HEADER = "id"

_HEADER_SEPARATORS = re.compile(r"[^a-z0-9]+")


@frozen
class _CleanedRows:
    rows: list[dict[str, str]]
    columns: list[str]
    dropped_invalid_email: int
    dropped_duplicate_email: int
    dropped_too_large: int


def start_recipient_list_import(
    *, team: Team, user: User | None, name: str, rows: list[dict[str, str]]
) -> RecipientListSummary:
    if len(rows) > MAX_RECIPIENT_LIST_ROWS:
        raise RecipientListInvalid(
            f"This file has {len(rows):,} rows. A file can have up to {MAX_RECIPIENT_LIST_ROWS:,}."
        )

    cleaned = _clean_rows(rows)
    if not cleaned.rows:
        raise RecipientListInvalid("No row has a valid email address.")

    distinct_ids = _resolve_distinct_ids(team, user, cleaned.rows)
    kept: dict[str, dict[str, str]] = {}
    dropped_duplicate_distinct_id = 0
    for row, distinct_id in zip(cleaned.rows, distinct_ids):
        # A row with no person yet becomes one, keyed by the file's distinct ID or else its email.
        resolved = distinct_id or row["email"]
        if resolved in kept:
            dropped_duplicate_distinct_id += 1
            continue
        kept[resolved] = row

    new_people = len(kept) - len(existing_distinct_ids(team.id, list(kept)))
    if new_people:
        _check_email_writable(team, user)

    with transaction.atomic():
        cohort = Cohort.objects.create(team_id=team.id, name=name, is_static=True, is_calculating=True, created_by=user)
        recipient_list = RecipientList.objects.for_team(team.id).create(
            team=team, cohort_id=cohort.pk, columns=cleaned.columns, created_by=user
        )
        RecipientListRow.objects.for_team(team.id).bulk_create(
            [
                # bulk_create skips save(), which moves the team to its parent, so the rows take the list's team.
                RecipientListRow(
                    team_id=recipient_list.team_id, recipient_list=recipient_list, distinct_id=distinct_id, data=row
                )
                for distinct_id, row in kept.items()
            ],
            batch_size=ROW_WRITE_BATCH_SIZE,
        )

    # The task module imports this one, so a module-level import would be circular.
    from products.workflows.backend.tasks.recipient_lists import capture_recipient_list_people  # noqa: PLC0415

    try:
        capture_recipient_list_people.delay(team_id=team.id, recipient_list_id=str(recipient_list.id))
    except Exception:
        # No task would finish this cohort, and the stuck-cohort sweep skips uploads.
        fail_recipient_list_import(team.id, recipient_list.id)
        raise

    return RecipientListSummary(
        id=recipient_list.id,
        cohort_id=cohort.pk,
        row_count=len(kept),
        new_people=new_people,
        columns=cleaned.columns,
        dropped_invalid_email=cleaned.dropped_invalid_email,
        dropped_duplicate_email=cleaned.dropped_duplicate_email + dropped_duplicate_distinct_id,
        dropped_too_large=cleaned.dropped_too_large,
    )


def get_recipient_list(team_id: int, recipient_list_id: UUID | str) -> RecipientList | None:
    return RecipientList.objects.for_team(team_id).filter(pk=recipient_list_id).first()


def recipient_lists_for_cohorts(team_id: int, cohort_ids: list[int]) -> list[RecipientListColumns]:
    recipient_lists = RecipientList.objects.for_team(team_id).filter(cohort_id__in=cohort_ids).order_by("created_at")
    return [
        RecipientListColumns(id=recipient_list.id, cohort_id=recipient_list.cohort_id, columns=recipient_list.columns)
        for recipient_list in recipient_lists
    ]


def mark_recipient_list_cohort_deleted(team_id: int, cohort_id: int, deleted: bool) -> None:
    recipient_lists = RecipientList.objects.for_team(team_id).filter(cohort_id=cohort_id)
    if deleted:
        recipient_lists.filter(cohort_deleted_at__isnull=True).update(cohort_deleted_at=timezone.now())
    else:
        recipient_lists.filter(cohort_deleted_at__isnull=False).update(cohort_deleted_at=None)


def delete_recipient_list_for_cohort(team_id: int, cohort_id: int) -> None:
    RecipientList.objects.for_team(team_id).filter(cohort_id=cohort_id).delete()


def delete_recipient_lists_of_deleted_cohorts() -> int:
    """A deleted cohort can't be sent to, so its list's rows have no use and are personal data to remove."""
    # Cross-team by design: one sweep covers every team.
    expired = RecipientList.objects.unscoped().filter(cohort_deleted_at__lt=timezone.now() - DELETED_COHORT_RETENTION)
    deleted, _ = expired.delete()
    return deleted


def fail_stalled_recipient_list_imports() -> int:
    """Fails imports whose cohort is still calculating after they should have finished.

    A task that dies, or can't schedule the next one, leaves the cohort calculating with nothing to finish it.
    The stuck-cohort sweep skips uploaded cohorts, so this one ends them and the cohort shows the error.
    """
    now = timezone.now()
    # Cross-team by design: one sweep covers every team.
    candidates = dict(
        RecipientList.objects.unscoped()
        .filter(created_at__lt=now - STALLED_IMPORT_AFTER, created_at__gte=now - STALLED_IMPORT_LOOKBACK)
        .values_list("cohort_id", "id")
    )
    stalled = Cohort.objects.filter(pk__in=list(candidates), is_calculating=True).values_list("pk", "team_id")
    failed = 0
    for cohort_id, cohort_team_id in stalled:
        fail_recipient_list_import(cohort_team_id, candidates[cohort_id])
        failed += 1
    return failed


def list_emails_by_distinct_id(team_id: int, recipient_list_id: UUID | str) -> dict[str, str]:
    rows = (
        RecipientListRow.objects.for_team(team_id)
        .filter(recipient_list_id=recipient_list_id)
        .values_list("distinct_id", "data__email")
    )
    return {distinct_id: str(email) for distinct_id, email in rows}


def fail_recipient_list_import(team_id: int, recipient_list_id: UUID | str) -> None:
    """Ends an import that can't finish: the cohort stops calculating and shows an error, and the rows go."""
    recipient_list = get_recipient_list(team_id, recipient_list_id)
    if recipient_list is None:
        return
    Cohort.objects.filter(pk=recipient_list.cohort_id, team_id=team_id).update(
        is_calculating=False, errors_calculating=F("errors_calculating") + 1, last_error_at=timezone.now()
    )
    try:
        recipient_list.delete()
    except Exception:
        logger.exception("recipient_list_cleanup_failed", team_id=team_id, recipient_list_id=str(recipient_list_id))


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
        for header, value in raw.items():
            key = _column_key(header, id_names_distinct_id)
            if not key:
                # Skipping a column that holds data would lose that data without saying so.
                if str(value).strip():
                    raise RecipientListInvalid("A column with data in it has no name. Name it and try again.")
                continue
            if key in row:
                # Keeping either value would give the template the wrong one without saying so.
                raise RecipientListInvalid(f'Two columns are both named "{key}". Rename one and try again.')
            row[key] = str(value).strip()
        has_email_column = has_email_column or "email" in row
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
        if len(json.dumps(row).encode()) > MAX_RECIPIENT_LIST_ROW_BYTES:
            dropped_too_large += 1
            continue
        seen_emails.add(email.lower())
        columns.update(dict.fromkeys(key for key in row if key != "distinct_id"))
        kept.append(row)
    if not has_email_column:
        raise RecipientListInvalid('Add a column named "email" with each person\'s address.')
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
        raise RecipientListInvalid(
            f"The distinct_id on row {line} is longer than {MAX_DISTINCT_ID_BYTES} bytes. Shorten it and try again."
        )
    if distinct_id.lower() in ILLEGAL_DISTINCT_IDS:
        raise RecipientListInvalid(
            f'Row {line} has the distinct_id "{distinct_id}", which PostHog can\'t use for a person. '
            "Use the person's ID from your app, or leave it empty to match by email."
        )


def _check_email_writable(team: Team, user: User | None) -> None:
    non_writable = get_non_writable_property_names(
        team_id=team.id, user=user, property_type=PropertyDefinition.Type.PERSON
    )
    if "email" in non_writable:
        raise RecipientListInvalid(
            "Some people in this file aren't in PostHog yet. Creating them sets the email person property, "
            "which you can't change. Remove those rows, or ask an admin for edit access to email."
        )


def _resolve_distinct_ids(team: Team, user: User | None, rows: list[dict[str, str]]) -> list[str | None]:
    """The distinct ID each row belongs to: its own column first, then an existing person with the email."""
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
    uuid_by_email = {email: UUID(str(person_uuid)) for email, person_uuid in response.results}
    id_by_uuid = {
        UUID(str(person_uuid)): person_id
        for person_id, person_uuid in get_person_ids_and_uuids_by_uuids(
            team.id, [str(person_uuid) for person_uuid in set(uuid_by_email.values())]
        )
    }
    # Any of the person's distinct IDs will do: a broadcast matches a row by all of them.
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
    """The identity column a header names, or else the header itself as the variable name."""
    loose = _loose_header(header)
    if loose in _IDENTITY_HEADERS:
        return loose
    if loose == _ID_HEADER and id_names_distinct_id:
        return "distinct_id"
    return str(header).strip()
