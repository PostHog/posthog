import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team, User

_RECIPIENTS_QUERY = """
SELECT
    address,
    groupArrayIf(preferences, source_kind = 'preference') AS preference_maps,
    maxIf(changed_at, source_kind = 'preference') AS preferences_updated_at,
    anyIf(suppression_source, source_kind = 'suppression') AS suppression_source,
    anyIf(suppression_reason, source_kind = 'suppression') AS suppression_reason,
    maxIf(changed_at, source_kind = 'suppression') AS suppressed_at,
    countIf(source_kind = 'suppression') > 0 AS is_suppressed,
    countIf(source_kind = 'person') AS person_count,
    arraySlice(arraySort(groupArrayIf(tuple(person_id, distinct_id, person_name), source_kind = 'person')), 1, 3) AS persons
FROM (
    SELECT
        'preference' AS source_kind,
        lower(trim(identifier)) AS address,
        preferences,
        updated_at AS changed_at,
        '' AS suppression_source,
        '' AS suppression_reason,
        '' AS person_id,
        '' AS distinct_id,
        '' AS person_name
    FROM system.message_recipient_preferences
    WHERE deleted = 0
    UNION ALL
    SELECT
        'suppression' AS source_kind,
        identifier AS address,
        '' AS preferences,
        suppressed_at AS changed_at,
        source AS suppression_source,
        ifNull(reason, '') AS suppression_reason,
        '' AS person_id,
        '' AS distinct_id,
        '' AS person_name
    FROM system.message_suppressions
    WHERE deleted = 0 AND suppressed
    UNION ALL
    SELECT
        'person' AS source_kind,
        coalesce(lower(trim(persons.properties.email)), '') AS address,
        '' AS preferences,
        NULL AS changed_at,
        '' AS suppression_source,
        '' AS suppression_reason,
        toString(persons.id) AS person_id,
        min(persons.pdi.distinct_id) AS distinct_id,
        coalesce(any(persons.properties.name), '') AS person_name
    FROM persons
    WHERE address != ''
    GROUP BY persons.id, address
)
WHERE {address_filter}
GROUP BY address
HAVING {facet_filter}
ORDER BY address
LIMIT {limit}
"""


@frozen
class RecipientQuery:
    limit: int


@frozen
class RecipientPerson:
    uuid: str
    distinct_id: str
    name: str | None


@frozen
class RecipientSuppression:
    source: str
    reason: str | None
    suppressed_at: datetime | None


@frozen
class Recipient:
    email: str
    all_marketing: str
    topics: dict[str, str]
    suppression: RecipientSuppression | None
    persons: list[RecipientPerson]
    person_count: int
    last_sent_at: datetime | None
    preferences_updated_at: datetime | None


@frozen
class RecipientPage:
    results: list[Recipient]
    next_cursor: str | None


def list_recipients(team: "Team", user: "User", query: RecipientQuery) -> RecipientPage:
    rows = _query_recipient_rows(team, user, query)
    return RecipientPage(results=[_build_recipient(row) for row in rows], next_cursor=None)


def _query_recipient_rows(team: "Team", user: "User", query: RecipientQuery) -> list[tuple[Any, ...]]:
    select = parse_select(
        _RECIPIENTS_QUERY,
        placeholders={
            "address_filter": ast.Constant(value=True),
            "facet_filter": ast.Constant(value=True),
            "limit": ast.Constant(value=query.limit),
        },
    )
    response = execute_hogql_query(select, team=team, user=user, query_type="MessagingRecipientsQuery")
    return response.results or []


def _build_recipient(row: tuple[Any, ...]) -> Recipient:
    (
        address,
        preference_maps,
        preferences_updated_at,
        suppression_source,
        suppression_reason,
        suppressed_at,
        is_suppressed,
        person_count,
        persons,
    ) = row
    return Recipient(
        email=address,
        all_marketing="NO_PREFERENCE",
        topics={},
        suppression=None,
        persons=[],
        person_count=person_count,
        last_sent_at=None,
        preferences_updated_at=None,
    )


def _parse_preferences(raw: str) -> dict[str, str]:
    return json.loads(raw) if raw else {}
