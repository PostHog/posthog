import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.dataclasses import frozen

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from products.messaging.backend.models.message_suppression import SuppressionSource

if TYPE_CHECKING:
    from posthog.models import Team, User

_RECIPIENTS_QUERY = """
SELECT
    address,
    groupArrayIf(preferences, source_kind = 'preference') AS preference_maps,
    maxIf(changed_at, source_kind = 'preference') AS preferences_updated_at,
    anyIf(suppression_source, source_kind = 'suppression') AS active_suppression_source,
    anyIf(suppression_reason, source_kind = 'suppression') AS active_suppression_reason,
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

_LAST_SENT_QUERY = """
SELECT lower(latest_recipient) AS address, max(latest_sent_at)
FROM (
    SELECT
        argMax(recipient, version) AS latest_recipient,
        argMax(sent_at, version) AS latest_sent_at,
        argMax(is_deleted, version) AS latest_is_deleted
    FROM message_assets
    WHERE team_id = %(team_id)s
      AND kind = 'email'
      AND sent_at >= now() - INTERVAL 30 DAY
      AND lower(recipient) IN %(addresses)s
    GROUP BY invocation_id, action_id
)
WHERE latest_is_deleted = 0
GROUP BY address
"""

_PERSONS_WITHOUT_EMAIL_QUERY = "SELECT count() FROM persons WHERE properties.email IS NULL"

ALL_MARKETING_TOPIC_KEY = "all-marketing"


class RecipientFacet(StrEnum):
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    NO_PREFERENCE = "no-preference"
    SUPPRESSED = "suppressed"
    PERSON = "person"
    PREFERENCE = "preference"


_TOPIC_STATUS_COUNT = "countIf(source_kind = 'preference' AND JSONExtractString(preferences, {topic_id}) = '%s')"

_TOPIC_CONDITIONS: dict[RecipientFacet, str] = {
    RecipientFacet.SUBSCRIBED: f"{_TOPIC_STATUS_COUNT % 'OPTED_OUT'} = 0 AND {_TOPIC_STATUS_COUNT % 'OPTED_IN'} > 0",
    RecipientFacet.UNSUBSCRIBED: f"{_TOPIC_STATUS_COUNT % 'OPTED_OUT'} > 0",
    RecipientFacet.NO_PREFERENCE: f"{_TOPIC_STATUS_COUNT % 'OPTED_OUT'} = 0 AND {_TOPIC_STATUS_COUNT % 'OPTED_IN'} = 0",
}

_VALUE_CONDITIONS: dict[tuple[RecipientFacet, str], str] = {
    **{
        (RecipientFacet.SUPPRESSED, source): "countIf(source_kind = 'suppression' AND suppression_source = {value}) > 0"
        for source in SuppressionSource.values
    },
    (RecipientFacet.PERSON, "linked"): "countIf(source_kind = 'person') > 0",
    (RecipientFacet.PERSON, "none"): "countIf(source_kind = 'person') = 0",
    (RecipientFacet.PREFERENCE, "recorded"): "countIf(source_kind = 'preference') > 0",
    (RecipientFacet.PREFERENCE, "none"): "countIf(source_kind = 'preference') = 0",
}


class InvalidRecipientFilter(ValueError):
    pass


@frozen
class RecipientFilter:
    facet: RecipientFacet
    value: str
    negated: bool


@frozen
class RecipientQuery:
    limit: int
    search: str | None = None
    filters: tuple[RecipientFilter, ...] = ()
    cursor: str | None = None
    email: str | None = None


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


@frozen
class _Topics:
    ids_by_key: dict[str, str]

    @property
    def keys_by_id(self) -> dict[str, str]:
        return {topic_id: key for key, topic_id in self.ids_by_key.items()}

    def id_for(self, key: str) -> str:
        if key == ALL_MARKETING_TOPIC_KEY:
            return ALL_MESSAGE_PREFERENCE_CATEGORY_ID
        if key not in self.ids_by_key:
            raise InvalidRecipientFilter(f"Unknown topic `{key}`.")
        return self.ids_by_key[key]


def parse_recipient_filter(raw: str) -> RecipientFilter:
    negated = raw.startswith("-")
    facet_name, separator, value = raw.removeprefix("-").partition(":")
    if not separator or not value:
        raise InvalidRecipientFilter(f"`{raw}` is not a `facet:value` filter.")
    if facet_name not in RecipientFacet:
        raise InvalidRecipientFilter(f"Unknown facet `{facet_name}`.")
    facet = RecipientFacet(facet_name)
    if facet not in _TOPIC_CONDITIONS and (facet, value) not in _VALUE_CONDITIONS:
        raise InvalidRecipientFilter(f"Unknown value `{value}` for `{facet}`.")
    return RecipientFilter(facet=facet, value=value, negated=negated)


def normalize_address(email: str) -> str:
    return email.strip().lower()


def list_recipients(team: "Team", user: "User", query: RecipientQuery) -> RecipientPage:
    topics = _team_topics(team.id)
    rows = _query_recipient_rows(team, user, query, topics)
    page_rows = rows[: query.limit]
    last_sent_at = _last_sent_at_by_address(team.id, [row[0] for row in page_rows])
    keys_by_id = topics.keys_by_id
    return RecipientPage(
        results=[_build_recipient(row, keys_by_id, last_sent_at.get(row[0])) for row in page_rows],
        next_cursor=page_rows[-1][0] if len(rows) > query.limit else None,
    )


def find_recipient(team: "Team", user: "User", email: str) -> Recipient | None:
    page = list_recipients(team, user, RecipientQuery(limit=1, email=normalize_address(email)))
    return page.results[0] if page.results else None


def count_persons_without_email(team: "Team", user: "User") -> int:
    response = execute_hogql_query(
        _PERSONS_WITHOUT_EMAIL_QUERY, team=team, user=user, query_type="MessagingRecipientsCoverageQuery"
    )
    return response.results[0][0]


def _team_topics(team_id: int) -> _Topics:
    categories = MessageCategory.objects.filter(team_id=team_id, deleted=False).values_list("key", "id")
    return _Topics(ids_by_key={key: str(category_id) for key, category_id in categories})


def _query_recipient_rows(team: "Team", user: "User", query: RecipientQuery, topics: _Topics) -> list[tuple[Any, ...]]:
    select = parse_select(
        _RECIPIENTS_QUERY,
        placeholders={
            "address_filter": _address_filter(query),
            "facet_filter": _facet_filter(query.filters, topics),
            "limit": ast.Constant(value=query.limit + 1),
        },
    )
    response = execute_hogql_query(select, team=team, user=user, query_type="MessagingRecipientsQuery")
    return response.results or []


def _address_filter(query: RecipientQuery) -> ast.Expr:
    conditions: list[ast.Expr] = [ast.Constant(value=True)]
    if query.search:
        conditions.append(
            parse_expr(
                "position(address, {search}) > 0",
                placeholders={"search": ast.Constant(value=query.search.strip().lower())},
            )
        )
    if query.cursor:
        conditions.append(parse_expr("address > {cursor}", placeholders={"cursor": ast.Constant(value=query.cursor)}))
    if query.email:
        conditions.append(parse_expr("address = {email}", placeholders={"email": ast.Constant(value=query.email)}))
    return ast.And(exprs=conditions)


def _last_sent_at_by_address(team_id: int, addresses: list[str]) -> dict[str, datetime]:
    if not addresses:
        return {}
    rows = sync_execute(_LAST_SENT_QUERY, {"team_id": team_id, "addresses": addresses})
    return dict(rows)


def _facet_filter(filters: Iterable[RecipientFilter], topics: _Topics) -> ast.Expr:
    filters_by_facet: dict[RecipientFacet, list[RecipientFilter]] = defaultdict(list)
    for recipient_filter in filters:
        filters_by_facet[recipient_filter.facet].append(recipient_filter)
    return ast.And(
        exprs=[_facet_group_filter(group, topics) for group in filters_by_facet.values()] or [ast.Constant(value=True)]
    )


def _facet_group_filter(filters: list[RecipientFilter], topics: _Topics) -> ast.Expr:
    matches_any = [_facet_condition(f, topics) for f in filters if not f.negated]
    matches_none = [ast.Not(expr=_facet_condition(f, topics)) for f in filters if f.negated]
    return ast.And(exprs=([ast.Or(exprs=matches_any)] if matches_any else []) + matches_none)


def _facet_condition(recipient_filter: RecipientFilter, topics: _Topics) -> ast.Expr:
    if recipient_filter.facet in _TOPIC_CONDITIONS:
        return parse_expr(
            _TOPIC_CONDITIONS[recipient_filter.facet],
            placeholders={"topic_id": ast.Constant(value=topics.id_for(recipient_filter.value))},
        )
    return parse_expr(
        _VALUE_CONDITIONS[(recipient_filter.facet, recipient_filter.value)],
        placeholders={"value": ast.Constant(value=recipient_filter.value)},
    )


def _build_recipient(
    row: tuple[Any, ...], topic_keys_by_id: dict[str, str], last_sent_at: datetime | None
) -> Recipient:
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
        last_sent_at=last_sent_at,
        preferences_updated_at=preferences_updated_at if preference_maps else None,
    )


def _merge_preferences(preference_maps: list[dict[str, str]]) -> dict[str, PreferenceStatus]:
    merged: dict[str, PreferenceStatus] = {}
    for preferences in preference_maps:
        for topic_id, status in preferences.items():
            if status == PreferenceStatus.OPTED_OUT or (status == PreferenceStatus.OPTED_IN and topic_id not in merged):
                merged[topic_id] = PreferenceStatus(status)
    return merged
