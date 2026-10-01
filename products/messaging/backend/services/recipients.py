import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus

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
    topic_keys_by_id = _topic_keys_by_id(team.id)
    rows = _query_recipient_rows(team, user, query)
    return RecipientPage(results=[_build_recipient(row, topic_keys_by_id) for row in rows], next_cursor=None)


def _topic_keys_by_id(team_id: int) -> dict[str, str]:
    categories = MessageCategory.objects.filter(team_id=team_id, deleted=False).values_list("id", "key")
    return {str(category_id): key for category_id, key in categories}


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


def _build_recipient(row: tuple[Any, ...], topic_keys_by_id: dict[str, str]) -> Recipient:
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
    statuses = _merge_preferences([json.loads(raw) for raw in preference_maps])
    return Recipient(
        email=address,
        all_marketing=statuses.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus.NO_PREFERENCE),
        topics={
            topic_keys_by_id[topic_id]: status for topic_id, status in statuses.items() if topic_id in topic_keys_by_id
        },
        suppression=RecipientSuppression(
            source=suppression_source, reason=suppression_reason or None, suppressed_at=suppressed_at
        )
        if is_suppressed
        else None,
        persons=[
            RecipientPerson(uuid=person_id, distinct_id=distinct_id, name=name or None)
            for person_id, distinct_id, name in persons
        ],
        person_count=person_count,
        last_sent_at=None,
        preferences_updated_at=preferences_updated_at if preference_maps else None,
    )


def _merge_preferences(preference_maps: list[dict[str, str]]) -> dict[str, PreferenceStatus]:
    merged: dict[str, PreferenceStatus] = {}
    for preferences in preference_maps:
        for topic_id, status in preferences.items():
            if status == PreferenceStatus.OPTED_OUT or (status == PreferenceStatus.OPTED_IN and topic_id not in merged):
                merged[topic_id] = PreferenceStatus(status)
    return merged
