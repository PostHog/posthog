import time
from typing import TYPE_CHECKING, cast

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.person.util import get_person_uuids_and_matched_distinct_ids
from posthog.models.team.team import Team
from posthog.models.user import User

from products.cohorts.backend.models.cohort import DEFAULT_COHORT_INSERT_BATCH_SIZE, Cohort
from products.cohorts.backend.models.util import delete_cohort_members_bulk
from products.workflows.backend.facade.contracts import (
    PreviousRecipients,
    PreviousRecipientsTimedOut,
    TooManyPreviousRecipients,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

# Inserting the people runs inside the request, so the list stays small enough to finish quickly.
MAX_PREVIOUS_RECIPIENTS = 20_000
MAX_COHORT_NAME_LENGTH = 400
# Both lookups run while the person waits on the entry point.
QUERY_TIMEOUT_SECONDS = 10
# The frontend gives up after 20 seconds, so writing the cohort stops before that and the worker is freed.
POPULATION_DEADLINE_SECONDS = 15


@frozen
class _PreviousSends:
    distinct_ids: list[str]
    emails: list[str]


def _previous_sends(
    team_id: int, source_record: str, limit: int, user_access_control: "UserAccessControl"
) -> _PreviousSends:
    """
    Who any workflow started from this record emailed, as far back as the sent-email log keeps. Only workflows the
    caller can see count. Each send collapses to its latest version first, so a send deleted since does not count.
    """
    flows = user_access_control.filter_queryset_by_access_level(
        HogFlow.objects.filter(team_id=team_id, source_record=source_record), resource="hog_flow"
    )
    flow_ids = [str(flow_id) for flow_id in flows.values_list("id", flat=True)]
    if not flow_ids:
        return _PreviousSends(distinct_ids=[], emails=[])
    with tags_context(product=Product.WORKFLOWS, feature=Feature.QUERY):
        rows = sync_execute(
            """
            SELECT latest_distinct_id, lower(trim(latest_recipient))
            FROM (
                SELECT
                    invocation_id,
                    action_id,
                    argMax(distinct_id, version) AS latest_distinct_id,
                    argMax(recipient, version) AS latest_recipient,
                    argMax(kind, version) AS latest_kind,
                    argMax(status, version) AS latest_status,
                    argMax(is_deleted, version) AS latest_is_deleted
                FROM message_assets
                WHERE team_id = %(team_id)s
                  AND function_kind = 'hog_flow'
                  AND function_id IN %(flow_ids)s
                GROUP BY invocation_id, action_id
            )
            WHERE latest_kind = 'email' AND latest_status = 'sent' AND latest_is_deleted = 0
            GROUP BY 1, 2
            LIMIT %(limit)s
            """,
            {"team_id": team_id, "flow_ids": flow_ids, "limit": limit},
            settings={"max_execution_time": QUERY_TIMEOUT_SECONDS, "timeout_overflow_mode": "throw"},
        )
    rows = cast(list, rows)
    if len(rows) >= limit:
        # A cut-off history would leave some recipients out of the exclusion, and they would get the email again.
        raise TooManyPreviousRecipients(MAX_PREVIOUS_RECIPIENTS)
    return _PreviousSends(
        distinct_ids=sorted({str(row[0]) for row in rows if row[0]}),
        emails=sorted({str(row[1]) for row in rows if row[1]}),
    )


def _person_ids_with_emails(team: Team, user: User, emails: list[str], limit: int) -> list[str]:
    """
    Every person whose email matches an address already emailed. A broadcast sends once per address, so a second
    profile with the same address would otherwise get the email the first one already got.
    """
    if not emails:
        return []
    query = parse_select(
        """
        SELECT id FROM persons
        WHERE lower(trim(toString(properties.email))) IN {emails}
        LIMIT {limit}
        """,
        placeholders={
            "emails": ast.Tuple(exprs=[ast.Constant(value=email) for email in emails]),
            "limit": ast.Constant(value=limit),
        },
    )
    with tags_context(product=Product.WORKFLOWS, feature=Feature.QUERY):
        response = execute_hogql_query(
            query=query,
            team=team,
            # The caller's property access applies, so the lookup reads only emails they may see.
            user=user,
            workload=Workload.OFFLINE,
            # A partial answer would leave people out of the exclusion, so a slow lookup fails instead.
            settings=HogQLGlobalSettings(max_execution_time=QUERY_TIMEOUT_SECONDS, timeout_overflow_mode="throw"),
        )
    return [str(row[0]) for row in response.results or []]


def build_previous_recipients_cohort(
    *, team: Team, user: User, user_access_control: "UserAccessControl", source_record: str, cohort_name: str
) -> PreviousRecipients:
    """
    Save the people already emailed from this record as a static cohort, so a new broadcast from the
    same record can leave them out of its audience. No cohort is made when nobody was emailed yet.
    """
    sends = _previous_sends(team.id, source_record, MAX_PREVIOUS_RECIPIENTS + 1, user_access_control)
    if not sends.distinct_ids and not sends.emails:
        return PreviousRecipients(cohort_id=None, people=0)
    # Distinct IDs, not stored person IDs, so a person merged since the send still matches.
    by_distinct_id, _ = get_person_uuids_and_matched_distinct_ids(team.id, sends.distinct_ids)
    person_ids = sorted(
        {*by_distinct_id, *_person_ids_with_emails(team, user, sends.emails, MAX_PREVIOUS_RECIPIENTS + 1)}
    )
    if not person_ids:
        return PreviousRecipients(cohort_id=None, people=0)
    if len(person_ids) > MAX_PREVIOUS_RECIPIENTS:
        raise TooManyPreviousRecipients(MAX_PREVIOUS_RECIPIENTS)
    cohort = Cohort.objects.create(
        team_id=team.id,
        name=cohort_name[:MAX_COHORT_NAME_LENGTH],
        is_static=True,
        is_calculating=True,
        created_by=user,
    )
    try:
        _populate_within_deadline(cohort, team.id, person_ids)
    except Exception:
        # A half-filled exclusion would let some of these people get the email twice.
        try:
            delete_cohort_members_bulk(team.id, [cohort.id])
        except Exception:
            # The cohort row goes either way, so nothing points at memberships this cleanup leaves behind.
            logger.warning("previous_recipients_cleanup_failed", cohort_id=cohort.id, exc_info=True)
        cohort.delete()
        raise
    cohort.refresh_from_db()
    # A failed recount leaves count empty although the members are in, so fall back to the people written.
    return PreviousRecipients(cohort_id=cohort.id, people=cohort.count if cohort.count is not None else len(person_ids))


def _populate_within_deadline(cohort: Cohort, team_id: int, person_ids: list[str]) -> None:
    """
    Write the members one batch at a time and stop once the deadline passes, so a slow store fails the request
    instead of holding the worker. Only the last batch recounts the cohort and saves its state.
    """
    deadline = time.monotonic() + POPULATION_DEADLINE_SECONDS
    batches = [
        person_ids[start : start + DEFAULT_COHORT_INSERT_BATCH_SIZE]
        for start in range(0, len(person_ids), DEFAULT_COHORT_INSERT_BATCH_SIZE)
    ]
    for index, batch in enumerate(batches):
        last = index == len(batches) - 1
        cohort.insert_users_list_by_uuid(batch, team_id=team_id, raise_on_error=True, save_state=last)
        if not last and time.monotonic() > deadline:
            raise PreviousRecipientsTimedOut()
