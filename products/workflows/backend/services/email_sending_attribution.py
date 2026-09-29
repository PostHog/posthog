import uuid as uuid_mod
from collections.abc import Mapping
from typing import Final

from django.db.models import QuerySet

from posthog.dataclasses import frozen

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob

# The app metric names the deliverability signals are read from. A Complaint (the recipient's
# "report spam" relayed through the provider's feedback loop) is recorded as `email_blocked`, and
# only permanent bounces count as `email_bounced_hard`, matching how AWS counts its bounce rate.
# See the SES webhook handler in nodejs/src/cdp/services/messaging/helpers/ses.ts.
SENT_METRIC: Final[str] = "email_sent"
HARD_BOUNCE_METRIC: Final[str] = "email_bounced_hard"
COMPLAINT_METRIC: Final[str] = "email_blocked"
EMAIL_HEALTH_METRIC_NAMES: Final[list[str]] = [SENT_METRIC, HARD_BOUNCE_METRIC, COMPLAINT_METRIC]


@frozen
class EmailSendingCounts:
    sent: int = 0
    bounced_hard: int = 0
    complained: int = 0

    def plus(self, counts: Mapping[str, int]) -> "EmailSendingCounts":
        return EmailSendingCounts(
            sent=self.sent + counts.get(SENT_METRIC, 0),
            bounced_hard=self.bounced_hard + counts.get(HARD_BOUNCE_METRIC, 0),
            complained=self.complained + counts.get(COMPLAINT_METRIC, 0),
        )


def looks_like_uuid(value: str) -> bool:
    try:
        uuid_mod.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


@frozen
class FlowEmailTotals:
    counts_by_flow: dict[str, EmailSendingCounts]
    names_by_flow_id: dict[str, str]


def fold_email_totals_by_flow(
    *,
    team_id: int,
    totals_by_source: Mapping[str, Mapping[str, int]],
    flows: QuerySet[HogFlow],
) -> FlowEmailTotals:
    """Attribute per-`app_source_id` email metric totals to the workflow that produced them.

    Email metrics are recorded under the workflow id for event-triggered runs and under the
    `HogFlowBatchJob` id for batch runs, so a batch send looks like an unrelated source until its
    job is resolved back to its parent workflow. A large batch send is the case that matters most
    here, so both are resolved and the batch counts are folded into the parent.

    `flows` scopes which workflows can be attributed to, which lets an access-controlled caller
    pass a filtered queryset. Sources matching neither a workflow nor a batch job (a deleted
    workflow, a non-UUID id) are dropped. Unnamed workflows come back as `""` so the name stays a
    plain string.
    """
    source_ids = [source_id for source_id in totals_by_source if looks_like_uuid(source_id)]
    # Only names are needed and HogFlow rows are wide (full step graphs in edges/actions/draft), so
    # don't hydrate model instances for an uncapped id list.
    names_by_flow_id = {
        str(flow_id): name or "" for flow_id, name in flows.filter(id__in=source_ids).values_list("id", "name")
    }
    unmatched_ids = [source_id for source_id in source_ids if source_id not in names_by_flow_id]
    batch_job_to_flow = {
        str(batch_job_id): str(flow_id)
        for batch_job_id, flow_id in HogFlowBatchJob.objects.filter(team_id=team_id, id__in=unmatched_ids).values_list(
            "id", "hog_flow_id"
        )
    }
    missing_flow_ids = set(batch_job_to_flow.values()) - set(names_by_flow_id)
    names_by_flow_id.update(
        {str(flow_id): name or "" for flow_id, name in flows.filter(id__in=missing_flow_ids).values_list("id", "name")}
    )

    counts_by_flow: dict[str, EmailSendingCounts] = {}
    for source_id, counts in totals_by_source.items():
        flow_id = source_id if source_id in names_by_flow_id else batch_job_to_flow.get(source_id)
        if flow_id is None or flow_id not in names_by_flow_id:
            continue
        counts_by_flow[flow_id] = counts_by_flow.get(flow_id, EmailSendingCounts()).plus(counts)

    return FlowEmailTotals(counts_by_flow=counts_by_flow, names_by_flow_id=names_by_flow_id)
