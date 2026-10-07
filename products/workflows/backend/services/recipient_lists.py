"""Uploaded recipient lists: a batch audience that brings its own rows and per-recipient variables."""

import re
import json
import uuid
from dataclasses import asdict

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team.team import Team
from posthog.storage import object_storage

from products.workflows.backend.facade.contracts import RecipientListPage, RecipientListRecipient, RecipientListSummary

RECIPIENT_LIST_AUDIENCE_TYPE = "recipient_list"
MAX_RECIPIENT_LIST_ROWS = 50_000
# Stays under HOG_FLOW_VARIABLES_MAX_BYTES so a row never trips the engine's variables limit.
MAX_RECIPIENT_ROW_BYTES = 4096
RECIPIENT_LIST_PAGE_SIZE = 500

_STORAGE_FOLDER = "workflows_recipient_lists"
_HEADER_SEPARATORS = re.compile(r"[^a-z0-9]+")


class RecipientListInvalid(Exception):
    """The upload or request cannot be used. The message is shown to the person who sent it."""


class RecipientListNotFound(Exception):
    pass


def is_recipient_list_audience(filters: dict | None) -> bool:
    return bool(filters) and filters.get("audience_type") == RECIPIENT_LIST_AUDIENCE_TYPE  # type: ignore[union-attr]


def create_recipient_list(*, team_id: int, rows: list[dict[str, str]]) -> RecipientListSummary:
    if len(rows) > MAX_RECIPIENT_LIST_ROWS:
        raise RecipientListInvalid(
            f"This list has {len(rows):,} rows. A list can have up to {MAX_RECIPIENT_LIST_ROWS:,}."
        )

    kept: list[dict] = []
    columns: dict[str, None] = {}
    seen_emails: set[str] = set()
    has_email_column = False
    dropped_invalid_email = dropped_duplicate_email = dropped_too_large = 0
    for raw in rows:
        row: dict[str, str] = {}
        for header, value in raw.items():
            key = _normalize_header(header)
            if not key and str(header).strip():
                # Dropping it would lose the column's data without saying so.
                raise RecipientListInvalid(
                    f'The column "{header}" needs a name with letters or numbers in it. Rename it and try again.'
                )
            if key in row:
                # Keeping either value would send the wrong address or data without saying so.
                raise RecipientListInvalid(f'Two columns are both named "{key}". Rename one and try again.')
            if key:
                row[key] = str(value).strip()
        has_email_column = has_email_column or "email" in row
        email = row.get("email", "")
        try:
            validate_email(email)
        except DjangoValidationError:
            dropped_invalid_email += 1
            continue
        if email.lower() in seen_emails:
            dropped_duplicate_email += 1
            continue
        if len(json.dumps(row).encode()) > MAX_RECIPIENT_ROW_BYTES:
            dropped_too_large += 1
            continue
        distinct_id = row.pop("distinct_id", "") or None
        seen_emails.add(email.lower())
        columns.update(dict.fromkeys(row))
        kept.append({"email": email, "distinct_id": distinct_id, "variables": row})

    if not has_email_column:
        raise RecipientListInvalid('Add a column named "email" with each recipient\'s address.')
    if not kept:
        raise RecipientListInvalid(
            "No row in this list has a valid email address. Check the email column and try again."
        )

    list_id = uuid.uuid4()
    pages = [kept[start : start + RECIPIENT_LIST_PAGE_SIZE] for start in range(0, len(kept), RECIPIENT_LIST_PAGE_SIZE)]
    for index, page in enumerate(pages):
        object_storage.write(
            _storage_key(team_id, list_id, f"page-{index}.json"),
            json.dumps({"rows": page, "has_more": index < len(pages) - 1}),
        )
    summary = RecipientListSummary(
        id=str(list_id),
        row_count=len(kept),
        columns=list(columns),
        dropped_invalid_email=dropped_invalid_email,
        dropped_duplicate_email=dropped_duplicate_email,
        dropped_too_large=dropped_too_large,
    )
    # Written last, so a list that has its summary also has every page.
    object_storage.write(_storage_key(team_id, list_id, "summary.json"), json.dumps(asdict(summary)))
    return summary


def get_recipient_list(*, team_id: int, list_id: object) -> RecipientListSummary | None:
    parsed = _parse_list_id(list_id)
    content = object_storage.read(_storage_key(team_id, parsed, "summary.json"), missing_ok=True) if parsed else None
    return RecipientListSummary(**json.loads(content)) if content else None


def get_recipient_list_page(*, team_id: int, list_id: object, cursor: str | None) -> RecipientListPage:
    try:
        index = int(cursor) if cursor else 0
    except ValueError:
        raise RecipientListInvalid("Invalid cursor.")
    parsed = _parse_list_id(list_id)
    content = (
        object_storage.read(_storage_key(team_id, parsed, f"page-{index}.json"), missing_ok=True) if parsed else None
    )
    if content is None:
        raise RecipientListNotFound()
    page = json.loads(content)
    rows = page["rows"]

    distinct_ids = [row["distinct_id"] for row in rows if row["distinct_id"]]
    persons_by_distinct_id = get_persons_mapped_by_distinct_id(team_id, distinct_ids) if distinct_ids else {}
    emails = [row["email"].lower() for row in rows if row["distinct_id"] not in persons_by_distinct_id]
    person_ids_by_email = _person_ids_by_email(team_id, emails) if emails else {}

    recipients = []
    for row in rows:
        person = persons_by_distinct_id.get(row["distinct_id"])
        recipients.append(
            RecipientListRecipient(
                email=row["email"],
                distinct_id=row["distinct_id"] if person else None,
                person_id=str(person.uuid) if person else person_ids_by_email.get(row["email"].lower()),
                variables=row["variables"],
            )
        )
    return RecipientListPage(
        recipients=recipients, cursor=str(index + 1) if page["has_more"] else None, has_more=page["has_more"]
    )


def _normalize_header(header: object) -> str:
    return _HEADER_SEPARATORS.sub("_", str(header).strip().lower()).strip("_")


def _parse_list_id(list_id: object) -> uuid.UUID | None:
    # The id reaches a storage path, so only a real UUID is allowed through.
    try:
        return uuid.UUID(str(list_id))
    except ValueError:
        return None


def _storage_key(team_id: int, list_id: uuid.UUID, name: str) -> str:
    return f"{_STORAGE_FOLDER}/team-{team_id}/{list_id}/{name}"


def _person_ids_by_email(team_id: int, emails: list[str]) -> dict[str, str]:
    # min(id) per normalized email is the same pick the email dedupe in batch_audience makes.
    query = parse_select(
        """
        SELECT lower(trim(toString(persons.properties.email))) AS normalized_email, min(persons.id) AS person_id
        FROM persons
        WHERE lower(trim(toString(persons.properties.email))) IN {emails}
        GROUP BY normalized_email
        LIMIT {limit}
        """,
        # Without a limit HogQL returns 100 rows, which is fewer than a page of recipients.
        placeholders={"emails": ast.Constant(value=emails), "limit": ast.Constant(value=len(emails))},
    )
    tag_queries(product=Product.WORKFLOWS, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=Team.objects.get(id=team_id), workload=Workload.OFFLINE)
    return {email: str(person_id) for email, person_id in response.results}
