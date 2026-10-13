from typing import cast

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team.team import Team
from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import PreviousRecipients, TooManyPreviousRecipients
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# Inserting the people runs inside the request, so the list stays small enough to finish quickly.
MAX_PREVIOUS_RECIPIENTS = 20_000
MAX_COHORT_NAME_LENGTH = 400


def previous_recipient_person_ids(team_id: int, source_record: str, limit: int) -> list[str]:
    """The people any workflow started from this record emailed, as far back as the sent-email log keeps."""
    flow_ids = [
        str(flow_id)
        for flow_id in HogFlow.objects.filter(team_id=team_id, source_record=source_record).values_list("id", flat=True)
    ]
    if not flow_ids:
        return []
    with tags_context(product=Product.WORKFLOWS, feature=Feature.QUERY):
        rows = sync_execute(
            """
            SELECT DISTINCT person_id
            FROM message_assets
            WHERE team_id = %(team_id)s
              AND function_kind = 'hog_flow'
              AND function_id IN %(flow_ids)s
              AND kind = 'email'
              AND status = 'sent'
              AND is_deleted = 0
              AND person_id != ''
            LIMIT %(limit)s
            """,
            {"team_id": team_id, "flow_ids": flow_ids, "limit": limit},
        )
    return [str(row[0]) for row in cast(list, rows)]


def build_previous_recipients_cohort(
    *, team: Team, user: User, source_record: str, cohort_name: str
) -> PreviousRecipients:
    """
    Save the people already emailed from this record as a static cohort, so a new broadcast from the
    same record can leave them out of its audience. No cohort is made when nobody was emailed yet.
    """
    person_ids = previous_recipient_person_ids(team.id, source_record, MAX_PREVIOUS_RECIPIENTS + 1)
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
        cohort.insert_users_list_by_uuid(person_ids, team_id=team.id, raise_on_error=True)
    except Exception:
        # A half-filled exclusion would let some of these people get the email twice.
        cohort.delete()
        raise
    cohort.refresh_from_db()
    return PreviousRecipients(cohort_id=cohort.id, people=cohort.count or 0)
