"""Identity of the person a recording is of, read from ClickHouse.

Person properties come from ClickHouse rather than personhog (see the person-data-access guidance), and the
query text is shared with the eval collector so a collected case carries the same identity production renders.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from posthog.hogql import ast
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

logger = structlog.get_logger(__name__)

# Person properties that conventionally hold the employer of the person recorded, most specific first. This is the
# person's own company, which is not always the account the session belongs to — an agency user working in a client's
# workspace carries their own employer here while the session's groups name the client.
PERSON_ORGANIZATION_KEYS = ("org__name", "organization_name", "organization", "company_name", "company")
# Full-name properties, most specific first; `first_name`/`last_name` are joined only when neither is set.
PERSON_NAME_KEYS = ("name", "full_name")
PERSON_NAME_PART_KEYS = ("first_name", "last_name")

# Every property the identity query reads, in the column order it returns them.
PERSON_IDENTITY_KEYS = ("email", *PERSON_NAME_KEYS, *PERSON_NAME_PART_KEYS, *PERSON_ORGANIZATION_KEYS)

# Person and group properties are customer-controlled free text of unbounded length, and they render into a prompt
# that is cached and re-sent on every turn. No real name, email, or company needs more than this.
MAX_IDENTITY_VALUE_LEN = 200

# Widens the window around the session so an event stamped slightly outside the recording's bounds still resolves.
# Exported so the eval collector can widen its window identically.
IDENTITY_TIMESTAMP_SLACK = dt.timedelta(hours=1)


def _person_identity_query() -> str:
    """`SELECT` over the subject's events in the session, one aggregate per identity property.

    Built from `PERSON_IDENTITY_KEYS` so the columns and the readers below cannot drift apart.

    The `distinct_id` clause is load-bearing, not an optimization. A project's write token is public by design,
    so anyone who knows a session id can post an event carrying it under a `distinct_id` of their choosing.
    Without the clause this aggregates over whoever shares the session id, and an arbitrary `any()` pick would
    be persisted as the subject and shown as authoritative. Bind to the distinct id the replay metadata names.
    """
    selects = ", ".join(
        f"any(person.properties.{escape_hogql_identifier(key)}) AS {escape_hogql_identifier(key)}"
        for key in PERSON_IDENTITY_KEYS
    )
    return (
        f"SELECT {selects} FROM events WHERE `$session_id` = {{session_id}} "
        "AND distinct_id = {distinct_id} AND timestamp >= {start} AND timestamp <= {end}"
    )


# Module-level so the eval collector can run the identical query through the query API.
SESSION_PERSON_IDENTITY_QUERY = _person_identity_query()


def fetch_session_person_properties(
    *, team: Team, session_id: str, distinct_id: str | None, start: dt.datetime, end: dt.datetime
) -> dict[str, Any]:
    """Identity properties of the person the recording is of, keyed by property name.

    `distinct_id` is the subject named by the replay metadata; without one there is no subject to attribute to,
    so the caller gets nothing rather than whatever else shares the session id.
    """
    if not distinct_id:
        return {}
    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    query = parse_select(
        SESSION_PERSON_IDENTITY_QUERY,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "distinct_id": ast.Constant(value=distinct_id),
            "start": ast.Constant(value=start - IDENTITY_TIMESTAMP_SLACK),
            "end": ast.Constant(value=end + IDENTITY_TIMESTAMP_SLACK),
        },
    )
    response = execute_hogql_query(query=query, team=team)
    if not response.results:
        return {}
    return person_properties_from_row(response.results[0])


def person_properties_from_row(row: Sequence[Any]) -> dict[str, Any]:
    """Zip a `SESSION_PERSON_IDENTITY_QUERY` result row back into a property dict.

    Unset properties are dropped: the query aggregates, so a session with no matching person still returns one
    row of nulls rather than no rows, and a dict of nulls would read as a person who carries every property blank.
    """
    return {key: value for key, value in zip(PERSON_IDENTITY_KEYS, row) if value is not None}


def clean_identity_value(value: Any) -> str | None:
    """A trimmed, length-capped string, or None — person properties hold blanks and non-strings alike."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_IDENTITY_VALUE_LEN]


def person_email(properties: Mapping[str, Any]) -> str | None:
    return clean_identity_value(properties.get("email"))


def person_display_name(properties: Mapping[str, Any]) -> str | None:
    """`name`, else first and last name joined; None when the person carries neither."""
    name = _first_value(properties, PERSON_NAME_KEYS)
    if name:
        return name
    parts = [part for key in PERSON_NAME_PART_KEYS if (part := clean_identity_value(properties.get(key)))]
    return " ".join(parts)[:MAX_IDENTITY_VALUE_LEN] or None


def person_organization(properties: Mapping[str, Any]) -> str | None:
    """The employer the recorded person carries, or None when they carry none of the conventional keys."""
    return _first_value(properties, PERSON_ORGANIZATION_KEYS)


def _first_value(properties: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    """The first of `keys` the person carries as a non-empty string, in the order given."""
    for key in keys:
        value = clean_identity_value(properties.get(key))
        if value:
            return value
    return None
