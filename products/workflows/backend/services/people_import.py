"""Uploaded people lists: each row creates or updates a person, and the people form a static cohort."""

import re
import json
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.storage import object_storage

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import PeopleImportSummary

MAX_PEOPLE_IMPORT_ROWS = 50_000
# Person properties are stored per person, so one row must not grow a profile without bound.
MAX_PEOPLE_IMPORT_ROW_BYTES = 4096
# Keeps each email lookup to one bounded HogQL query.
EMAIL_LOOKUP_CHUNK_SIZE = 1000

_STORAGE_FOLDER = "workflows_people_imports"
_HEADER_SEPARATORS = re.compile(r"[^a-z0-9]+")


class PeopleImportInvalid(Exception):
    """The upload cannot be used. The message is shown to the person who sent it."""


def start_people_import(*, team: Team, user: User | None, name: str, rows: list[dict[str, str]]) -> PeopleImportSummary:
    if len(rows) > MAX_PEOPLE_IMPORT_ROWS:
        raise PeopleImportInvalid(
            f"This file has {len(rows):,} rows. A file can have up to {MAX_PEOPLE_IMPORT_ROWS:,}."
        )

    kept, summary_counts, columns = _clean_rows(rows)
    if not kept:
        raise PeopleImportInvalid("No row has a valid email address.")

    distinct_ids = _resolve_distinct_ids(team, kept)
    people = []
    seen_distinct_ids: set[str] = set()
    for row, distinct_id in zip(kept, distinct_ids):
        # A row with no person yet becomes one, keyed by the CSV's distinct_id or else its email.
        resolved = distinct_id or row["email"]
        if resolved in seen_distinct_ids:
            summary_counts["dropped_duplicate_email"] += 1
            continue
        seen_distinct_ids.add(resolved)
        people.append({"distinct_id": resolved, "properties": row})

    existing = _existing_distinct_ids(team.id, [person["distinct_id"] for person in people])
    cohort = Cohort.objects.create(team_id=team.id, name=name, is_static=True, is_calculating=True, created_by=user)
    storage_key = f"{_STORAGE_FOLDER}/team-{team.id}/{cohort.pk}-{uuid.uuid4()}.json"
    object_storage.write(storage_key, json.dumps(people))

    # The task module imports this one, so a module-level import would be circular.
    from products.workflows.backend.tasks.people_import import capture_people_import  # noqa: PLC0415

    capture_people_import.delay(team_id=team.id, cohort_id=cohort.pk, storage_key=storage_key)

    return PeopleImportSummary(
        cohort_id=cohort.pk,
        row_count=len(people),
        new_people=sum(1 for person in people if person["distinct_id"] not in existing),
        columns=list(columns),
        **summary_counts,
    )


def read_people(storage_key: str) -> list[dict]:
    content = object_storage.read(storage_key, missing_ok=True)
    return json.loads(content) if content else []


def delete_people(storage_key: str) -> None:
    object_storage.delete(storage_key)


def _clean_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, int], dict[str, None]]:
    kept: list[dict[str, str]] = []
    columns: dict[str, None] = {}
    seen_emails: set[str] = set()
    has_email_column = False
    counts = {"dropped_invalid_email": 0, "dropped_duplicate_email": 0, "dropped_too_large": 0}
    for raw in rows:
        row: dict[str, str] = {}
        for header, value in raw.items():
            key = _normalize_header(header)
            if not key and str(header).strip():
                # Skipping it would lose the column's data without saying so.
                raise PeopleImportInvalid(
                    f'The column "{header}" needs a name with letters or numbers in it. Rename it and try again.'
                )
            if key in row:
                # Keeping either value would set the wrong property without saying so.
                raise PeopleImportInvalid(f'Two columns are both named "{key}". Rename one and try again.')
            if key:
                row[key] = str(value).strip()
        has_email_column = has_email_column or "email" in row
        email = row.get("email", "")
        try:
            validate_email(email)
        except DjangoValidationError:
            counts["dropped_invalid_email"] += 1
            continue
        if email.lower() in seen_emails:
            counts["dropped_duplicate_email"] += 1
            continue
        if len(json.dumps(row).encode()) > MAX_PEOPLE_IMPORT_ROW_BYTES:
            counts["dropped_too_large"] += 1
            continue
        seen_emails.add(email.lower())
        columns.update(dict.fromkeys(key for key in row if key != "distinct_id"))
        kept.append(row)
    if not has_email_column:
        raise PeopleImportInvalid('Add a column named "email" with each person\'s address.')
    return kept, counts, columns


def _resolve_distinct_ids(team: Team, rows: list[dict[str, str]]) -> list[str | None]:
    """The distinct ID each row writes to: its own column first, then an existing person with the email."""
    emails = [row["email"].lower() for row in rows if not row.get("distinct_id")]
    by_email: dict[str, str] = {}
    for start in range(0, len(emails), EMAIL_LOOKUP_CHUNK_SIZE):
        by_email.update(_distinct_ids_by_email(team, emails[start : start + EMAIL_LOOKUP_CHUNK_SIZE]))
    resolved: list[str | None] = []
    for row in rows:
        distinct_id = row.pop("distinct_id", "")
        resolved.append(distinct_id or by_email.get(row["email"].lower()))
    return resolved


def _distinct_ids_by_email(team: Team, emails: list[str]) -> dict[str, str]:
    if not emails:
        return {}
    # The lowest person ID per email is the same person the email dedupe of a filtered audience picks.
    query = parse_select(
        """
        SELECT lower(trim(toString(person.properties.email))) AS normalized_email,
            argMin(distinct_id, person_id) AS matched_distinct_id
        FROM person_distinct_ids
        WHERE lower(trim(toString(person.properties.email))) IN {emails}
        GROUP BY normalized_email
        LIMIT {limit}
        """,
        # Without a limit HogQL returns 100 rows, which is fewer than one chunk of emails.
        placeholders={"emails": ast.Constant(value=emails), "limit": ast.Constant(value=len(emails))},
    )
    tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=team, workload=Workload.OFFLINE)
    return {email: str(distinct_id) for email, distinct_id in response.results}


def _existing_distinct_ids(team_id: int, distinct_ids: list[str]) -> set[str]:
    found: set[str] = set()
    for start in range(0, len(distinct_ids), EMAIL_LOOKUP_CHUNK_SIZE):
        found.update(get_persons_mapped_by_distinct_id(team_id, distinct_ids[start : start + EMAIL_LOOKUP_CHUNK_SIZE]))
    return found


def _normalize_header(header: object) -> str:
    return _HEADER_SEPARATORS.sub("_", str(header).strip().lower()).strip("_")
