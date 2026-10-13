from typing import TYPE_CHECKING, cast

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import delete_cohort_members_bulk
from products.workflows.backend.facade.contracts import PreviousRecipients, TooManyPreviousRecipients
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

# Inserting the people runs inside the request, so the list stays small enough to finish quickly.
MAX_PREVIOUS_RECIPIENTS = 20_000
MAX_COHORT_NAME_LENGTH = 400


def previous_recipient_distinct_ids(
    team_id: int, source_record: str, limit: int, user_access_control: "UserAccessControl"
) -> list[str]:
    """
    The people any workflow started from this record emailed, as far back as the sent-email log keeps. Only
    workflows the caller can see count. Distinct IDs, not person IDs, so a person merged since the send still matches.
    """
    flows = user_access_control.filter_queryset_by_access_level(
        HogFlow.objects.filter(team_id=team_id, source_record=source_record), resource="hog_flow"
    )
    flow_ids = [str(flow_id) for flow_id in flows.values_list("id", flat=True)]
    if not flow_ids:
        return []
    with tags_context(product=Product.WORKFLOWS, feature=Feature.QUERY):
        rows = sync_execute(
            """
            SELECT DISTINCT distinct_id
            FROM message_assets
            WHERE team_id = %(team_id)s
              AND function_kind = 'hog_flow'
              AND function_id IN %(flow_ids)s
              AND kind = 'email'
              AND status = 'sent'
              AND is_deleted = 0
              AND distinct_id != ''
            LIMIT %(limit)s
            """,
            {"team_id": team_id, "flow_ids": flow_ids, "limit": limit},
        )
    return [str(row[0]) for row in cast(list, rows)]


def build_previous_recipients_cohort(
    *, team: Team, user: User, user_access_control: "UserAccessControl", source_record: str, cohort_name: str
) -> PreviousRecipients:
    """
    Save the people already emailed from this record as a static cohort, so a new broadcast from the
    same record can leave them out of its audience. No cohort is made when nobody was emailed yet.
    """
    distinct_ids = previous_recipient_distinct_ids(
        team.id, source_record, MAX_PREVIOUS_RECIPIENTS + 1, user_access_control
    )
    if not distinct_ids:
        return PreviousRecipients(cohort_id=None, people=0)
    if len(distinct_ids) > MAX_PREVIOUS_RECIPIENTS:
        raise TooManyPreviousRecipients(MAX_PREVIOUS_RECIPIENTS)
    cohort = Cohort.objects.create(
        team_id=team.id,
        name=cohort_name[:MAX_COHORT_NAME_LENGTH],
        is_static=True,
        is_calculating=True,
        created_by=user,
    )
    try:
        cohort.insert_users_by_list(distinct_ids, team_id=team.id, raise_on_error=True)
    except Exception:
        # A half-filled exclusion would let some of these people get the email twice.
        delete_cohort_members_bulk(team.id, [cohort.id])
        cohort.delete()
        raise
    cohort.refresh_from_db()
    # A failed recount leaves count empty although the members are in, so fall back to the distinct IDs written.
    return PreviousRecipients(
        cohort_id=cohort.id, people=cohort.count if cohort.count is not None else len(distinct_ids)
    )
