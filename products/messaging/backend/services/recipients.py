import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.dataclasses import frozen
from posthog.models.message_assets.sql import MESSAGE_ASSETS_TTL_DAYS

from products.messaging.backend.models.message_category import ALL_MARKETING_TOPIC_KEY, MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus
from products.messaging.backend.models.message_suppression import SuppressionSource

if TYPE_CHECKING:
    from posthog.models import Team, User

_RECIPIENTS_QUERY = """
SELECT
    address,
    groupArrayIf(preferences, source_kind = 'preference') AS preference_maps,
    maxIf(changed_at, source_kind = 'preference') AS preferences_updated_at,
    argMaxIf(suppression_source, changed_at, source_kind = 'suppression') AS active_suppression_source,
    argMaxIf(suppression_reason, changed_at, source_kind = 'suppression') AS active_suppression_reason,
    maxIf(changed_at, source_kind = 'suppression') AS suppressed_at,
    countIf(source_kind = 'suppression') > 0 AS is_suppressed,
    countIf(source_kind = 'person') AS person_count,
    arraySlice(arraySort(groupArrayIf(tuple(person_id, person_name), source_kind = 'person')), 1, 3) AS persons
FROM (
    SELECT
        'preference' AS source_kind,
        lowerUTF8(replaceRegexpAll(identifier, {surrounding_whitespace}, '')) AS address,
        preferences,
        updated_at AS changed_at,
        '' AS suppression_source,
        '' AS suppression_reason,
        '' AS person_id,
        '' AS person_name
    FROM system.message_recipient_preferences
    WHERE deleted = 0 AND address != '' AND {address_filter}
    UNION ALL
    SELECT
        'suppression' AS source_kind,
        lowerUTF8(replaceRegexpAll(identifier, {surrounding_whitespace}, '')) AS address,
        '' AS preferences,
        suppressed_at AS changed_at,
        source AS suppression_source,
        ifNull(reason, '') AS suppression_reason,
        '' AS person_id,
        '' AS person_name
    FROM system.message_suppressions
    WHERE deleted = 0 AND suppressed AND address != '' AND {address_filter}
    UNION ALL
    SELECT
        'person' AS source_kind,
        coalesce(lowerUTF8(replaceRegexpAll(persons.properties.email, {surrounding_whitespace}, '')), '') AS address,
        '' AS preferences,
        NULL AS changed_at,
        '' AS suppression_source,
        '' AS suppression_reason,
        toString(persons.id) AS person_id,
        coalesce(persons.properties.name, '') AS person_name
    FROM persons
    WHERE address != '' AND {address_filter}
)
GROUP BY address
HAVING {facet_filter}
ORDER BY address
LIMIT {limit}
"""

_LAST_SENT_QUERY = """
SELECT lowerUTF8(replaceRegexpAll(latest_recipient, %(surrounding_whitespace)s, '')) AS address, max(latest_sent_at)
FROM (
    SELECT
        argMax(recipient, version) AS latest_recipient,
        argMax(sent_at, version) AS latest_sent_at,
        argMax(is_deleted, version) AS latest_is_deleted
    FROM message_assets
    WHERE team_id = %(team_id)s
      AND kind = 'email'
      AND sent_at >= %(sent_after)s
      AND lowerUTF8(replaceRegexpAll(recipient, %(surrounding_whitespace)s, '')) IN %(addresses)s
    GROUP BY invocation_id, action_id
)
WHERE latest_is_deleted = 0
GROUP BY address
"""

_FIRST_DISTINCT_ID_QUERY = """
SELECT toString(person_id), min(distinct_id)
FROM (
    SELECT distinct_id, argMax(person_id, version) AS person_id, argMax(is_deleted, version) AS is_deleted
    FROM raw_person_distinct_ids
    WHERE distinct_id IN (SELECT distinct_id FROM raw_person_distinct_ids WHERE person_id IN {person_ids})
    GROUP BY distinct_id
)
WHERE is_deleted = 0 AND person_id IN {person_ids}
GROUP BY person_id
LIMIT {person_count}
"""

_PERSONS_WITHOUT_EMAIL_QUERY = """
SELECT count()
FROM persons
WHERE coalesce(replaceRegexpAll(persons.properties.email, {surrounding_whitespace}, ''), '') = ''
"""


LAST_SENT_WINDOW_DAYS = MESSAGE_ASSETS_TTL_DAYS

_JAVASCRIPT_TRIM_WHITESPACE = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_WHITESPACE_CLASS = "[" + "".join(f"\\x{{{ord(char):X}}}" for char in _JAVASCRIPT_TRIM_WHITESPACE) + "]"
_SURROUNDING_WHITESPACE_PATTERN = f"^{_WHITESPACE_CLASS}+|{_WHITESPACE_CLASS}+$"


class RecipientFacet(StrEnum):
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"
    NO_PREFERENCE = "no-preference"
    SUPPRESSED = "suppressed"
    PERSON = "person"
    PREFERENCE = "preference"


_OPTED_OUT_ROWS = "countIf(source_kind = 'preference' AND JSONExtractString(preferences, {topic_id}) = 'OPTED_OUT')"
_OPTED_IN_ROWS = "countIf(source_kind = 'preference' AND JSONExtractString(preferences, {topic_id}) = 'OPTED_IN')"

# Unsubscribed wins: one spelling of an address opting out outweighs another spelling opting in.
_TOPIC_CONDITIONS: dict[RecipientFacet, str] = {
    RecipientFacet.SUBSCRIBED: f"{_OPTED_OUT_ROWS} = 0 AND {_OPTED_IN_ROWS} > 0",
    RecipientFacet.UNSUBSCRIBED: f"{_OPTED_OUT_ROWS} > 0",
    RecipientFacet.NO_PREFERENCE: f"{_OPTED_OUT_ROWS} = 0 AND {_OPTED_IN_ROWS} = 0",
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
    source: SuppressionSource
    reason: str | None
    suppressed_at: datetime | None


@frozen
class Recipient:
    email: str
    all_marketing: PreferenceStatus
    topics: dict[str, PreferenceStatus]
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


def _normalize_address(email: str) -> str:
    return email.strip(_JAVASCRIPT_TRIM_WHITESPACE).lower()


def _team_topics(team_id: int) -> _Topics:
    categories = MessageCategory.objects.filter(team_id=team_id, deleted=False).values_list("key", "id")
    return _Topics(ids_by_key={key: str(category_id) for key, category_id in categories})


def _address_filter(query: RecipientQuery) -> ast.Expr:
    conditions: list[ast.Expr] = [ast.Constant(value=True)]
    if query.search:
        conditions.append(
            parse_expr(
                "positionUTF8(address, {search}) > 0",
                placeholders={"search": ast.Constant(value=_normalize_address(query.search))},
            )
        )
    if query.cursor:
        conditions.append(parse_expr("address > {cursor}", placeholders={"cursor": ast.Constant(value=query.cursor)}))
    if query.email:
        conditions.append(
            parse_expr("address = {email}", placeholders={"email": ast.Constant(value=_normalize_address(query.email))})
        )
    return ast.And(exprs=conditions)


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


def _facet_group_filter(filters: list[RecipientFilter], topics: _Topics) -> ast.Expr:
    matches_any: list[ast.Expr] = [_facet_condition(f, topics) for f in filters if not f.negated]
    conditions: list[ast.Expr] = [ast.Or(exprs=matches_any)] if matches_any else []
    conditions += [ast.Not(expr=_facet_condition(f, topics)) for f in filters if f.negated]
    return ast.And(exprs=conditions)


def _facet_filter(filters: Iterable[RecipientFilter], topics: _Topics) -> ast.Expr:
    filters_by_facet: dict[RecipientFacet, list[RecipientFilter]] = defaultdict(list)
    for recipient_filter in filters:
        filters_by_facet[recipient_filter.facet].append(recipient_filter)
    return ast.And(
        exprs=[_facet_group_filter(group, topics) for group in filters_by_facet.values()] or [ast.Constant(value=True)]
    )


def _query_recipient_rows(team: "Team", user: "User", query: RecipientQuery, topics: _Topics) -> list[tuple[Any, ...]]:
    select = parse_select(
        _RECIPIENTS_QUERY,
        placeholders={
            "address_filter": _address_filter(query),
            "surrounding_whitespace": ast.Constant(value=_SURROUNDING_WHITESPACE_PATTERN),
            "facet_filter": _facet_filter(query.filters, topics),
            "limit": ast.Constant(value=query.limit + 1),
        },
    )
    response = execute_hogql_query(select, team=team, user=user, query_type="MessagingRecipientsQuery")
    return response.results or []


def _last_sent_at_by_address(team_id: int, addresses: list[str]) -> dict[str, datetime]:
    if not addresses:
        return {}
    sent_after = timezone.now() - timedelta(days=LAST_SENT_WINDOW_DAYS)
    rows = sync_execute(
        _LAST_SENT_QUERY,
        {
            "team_id": team_id,
            "addresses": addresses,
            "sent_after": sent_after,
            "surrounding_whitespace": _SURROUNDING_WHITESPACE_PATTERN,
        },
        team_id=team_id,
    )
    return dict(rows)


def _previewed_person_ids(rows: list[tuple[Any, ...]]) -> list[str]:
    return [person_id for row in rows for person_id, _name in row[-1]]


def _first_distinct_id_by_person(team: "Team", user: "User", person_ids: list[str]) -> dict[str, str]:
    if not person_ids:
        return {}
    response = execute_hogql_query(
        _FIRST_DISTINCT_ID_QUERY,
        team=team,
        user=user,
        placeholders={
            "person_ids": ast.Constant(value=person_ids),
            "person_count": ast.Constant(value=len(person_ids)),
        },
        query_type="MessagingRecipientsDistinctIdsQuery",
    )
    return dict(response.results or [])


def _parse_preference_map(raw: str) -> dict[str, str]:
    preferences = json.loads(raw)
    return preferences if isinstance(preferences, dict) else {}


def _merge_preferences(preference_maps: list[dict[str, str]]) -> dict[str, PreferenceStatus]:
    merged: dict[str, PreferenceStatus] = {}
    for preferences in preference_maps:
        for topic_id, status in preferences.items():
            if status == PreferenceStatus.OPTED_OUT or (status == PreferenceStatus.OPTED_IN and topic_id not in merged):
                merged[topic_id] = PreferenceStatus(status)
    return merged


def _build_recipient(
    row: tuple[Any, ...],
    topic_keys_by_id: dict[str, str],
    last_sent_at: datetime | None,
    distinct_id_by_person: dict[str, str],
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
    statuses = _merge_preferences([_parse_preference_map(raw) for raw in preference_maps])
    return Recipient(
        email=address,
        all_marketing=statuses.get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID, PreferenceStatus.NO_PREFERENCE),
        topics={
            topic_keys_by_id[topic_id]: status for topic_id, status in statuses.items() if topic_id in topic_keys_by_id
        },
        suppression=RecipientSuppression(
            source=SuppressionSource(suppression_source),
            reason=suppression_reason or None,
            suppressed_at=suppressed_at,
        )
        if is_suppressed
        else None,
        persons=[
            RecipientPerson(uuid=person_id, distinct_id=distinct_id_by_person.get(person_id, ""), name=name or None)
            for person_id, name in persons
        ],
        person_count=person_count,
        last_sent_at=last_sent_at,
        preferences_updated_at=preferences_updated_at if preference_maps else None,
    )


def list_recipients(team: "Team", user: "User", query: RecipientQuery) -> RecipientPage:
    topics = _team_topics(team.id)
    rows = _query_recipient_rows(team, user, query, topics)
    page_rows = rows[: query.limit]
    last_sent_at = _last_sent_at_by_address(team.id, [row[0] for row in page_rows])
    distinct_ids = _first_distinct_id_by_person(team, user, _previewed_person_ids(page_rows))
    keys_by_id = topics.keys_by_id
    return RecipientPage(
        results=[_build_recipient(row, keys_by_id, last_sent_at.get(row[0]), distinct_ids) for row in page_rows],
        next_cursor=page_rows[-1][0] if len(rows) > query.limit else None,
    )


def count_persons_without_email(team: "Team", user: "User") -> int:
    response = execute_hogql_query(
        _PERSONS_WITHOUT_EMAIL_QUERY,
        team=team,
        user=user,
        placeholders={"surrounding_whitespace": ast.Constant(value=_SURROUNDING_WHITESPACE_PATTERN)},
        query_type="MessagingRecipientsCoverageQuery",
    )
    return response.results[0][0]
