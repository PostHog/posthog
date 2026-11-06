"""Ties received mail to the person who wrote it and the email it answers.

Both are extras on top of mail that already arrived, so a failed lookup leaves the link empty rather than costing the
mail or holding it up with retries.
"""

import re
from collections.abc import Iterable
from uuid import UUID

import structlog

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.messaging.backend.facade.transactional_email_log import find_sends_by_provider_message_ids
from products.workflows.backend.facade.enums import ReceivedEmailMatchMethod as MatchMethod

logger = structlog.get_logger(__name__)

_LOOKUP_TIMEOUT_SECONDS = 10
# SES overwrites Message-ID with `<ses message id>@<region or email>.amazonses.com`, so a reply names our send this way.
_SES_MESSAGE_ID = re.compile(r"^<([^@<>\s]+)@(?:[a-z0-9-]+\.)*amazonses\.com>$", re.IGNORECASE)

_PERSON_QUERY = """
SELECT person_id, distinct_id
FROM person_distinct_ids
WHERE lower(person.properties.email) = {email}
ORDER BY person.is_identified DESC, person.created_at ASC, distinct_id ASC
LIMIT 1
"""


@frozen
class PersonMatch:
    person_id: UUID
    distinct_id: str


@frozen
class SendMatch:
    message_id: UUID
    workflow_id: UUID | None
    method: MatchMethod


def find_person_by_email(team_id: int, email: str) -> PersonMatch | None:
    try:
        response = _run_person_query(team_id, email)
    except Exception:
        logger.warning("inbound_email_person_lookup_failed", team_id=team_id, exc_info=True)
        return None
    if not response.results:
        return None
    person_id, distinct_id = response.results[0]
    return PersonMatch(person_id=UUID(str(person_id)), distinct_id=str(distinct_id)[:400])


def find_original_send(team_id: int, *, in_reply_to: str, references: Iterable[str]) -> SendMatch | None:
    direct = ses_message_id(in_reply_to)
    # The newest reference sits last, so the closest message in the thread wins.
    referenced = [ses_id for reference in reversed(list(references)) if (ses_id := ses_message_id(reference))]
    candidates = [*([direct] if direct else []), *referenced]
    if not candidates:
        return None
    try:
        sends = find_sends_by_provider_message_ids(team_id, candidates)
    except Exception:
        logger.warning("inbound_email_send_lookup_failed", team_id=team_id, exc_info=True)
        return None
    for candidate in candidates:
        send = sends.get(candidate)
        if send is not None:
            method = MatchMethod.IN_REPLY_TO if candidate == direct else MatchMethod.REFERENCES
            return SendMatch(message_id=send.message_id, workflow_id=send.workflow_id, method=method)
    return None


def ses_message_id(header_value: str) -> str | None:
    match = _SES_MESSAGE_ID.match(header_value.strip())
    return match.group(1) if match else None


def _run_person_query(team_id: int, email: str) -> HogQLQueryResponse:
    team = Team.objects.get(pk=team_id)
    with tags_context(product=Product.MESSAGING, feature=Feature.QUERY, team_id=team_id):
        return execute_hogql_query(
            parse_select(_PERSON_QUERY),
            team=team,
            placeholders={"email": ast.Constant(value=email.lower())},
            query_type="inbound_email_person_match",
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=_LOOKUP_TIMEOUT_SECONDS),
        )
