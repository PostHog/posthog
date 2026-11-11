from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import requests
import structlog

from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.plugins.plugin_server_api import create_batch_hog_flow_job_invocation

from products.workflows.backend.facade.enums import HogFlowBatchJobState
from products.workflows.backend.services.batch_audience_cohorts import (
    realtime_audience_cohort,
    realtime_cohort_is_ready,
)
from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit, hog_flow_sends_email

if TYPE_CHECKING:
    from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)


class HogFlowBatchJob(RootTeamMixin, UUIDTModel):
    """
    Stores the status and other meta information for a batch of HogFlow jobs (typically used for a broadcast)
    """

    class Meta:
        indexes = [
            models.Index(fields=["team"]),
            # The minute-by-minute sweep reads only waiting runs, across every team.
            models.Index(
                fields=["created_at"],
                name="hogflowbatchjob_waiting_idx",
                condition=models.Q(status="waiting"),
            ),
        ]

    State = HogFlowBatchJobState

    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING, related_name="+")
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.DO_NOTHING)
    variables = models.JSONField(default=dict)
    filters = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED.value)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.DO_NOTHING, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"HogFlow batch run {self.id}"


def batch_job_audience_filters(job: HogFlowBatchJob) -> dict:
    """The audience the resolver reads: each key from the snapshot, or from the live trigger when the
    snapshot has none. The resolver resolves the keys the same way."""
    trigger_filters = (job.hog_flow.trigger or {}).get("filters") or {}
    snapshot = job.filters or {}
    return {
        key: snapshot[key] if snapshot.get(key) is not None else trigger_filters.get(key)
        for key in ("properties", "filter_test_accounts")
    }


# A run waits this long for its realtime cohort to finish calculating, then fails.
REALTIME_COHORT_WAIT_LIMIT = timedelta(hours=24)


def dispatch_batch_job(
    job: HogFlowBatchJob, realtime_cohort: "Cohort | None", *, wait_for_cohort: bool = False
) -> "requests.Response":
    cohort_target: dict | None = None
    if realtime_cohort is not None:
        cohort_target = {"id": realtime_cohort.pk, "team_id": realtime_cohort.team_id}
        if wait_for_cohort:
            # The resolver parks until a resume wakes it, and fails the run at this instant otherwise.
            cohort_target["wait_until"] = (job.created_at + REALTIME_COHORT_WAIT_LIMIT).isoformat()
    return create_batch_hog_flow_job_invocation(
        team_id=job.team.id,
        hog_flow_id=job.hog_flow.id,
        batch_job_id=job.id,
        max_audience_size=get_hogflow_batch_trigger_limit(
            job.team.id,
            # The dispatch runs the live config, so the live actions decide the channel.
            # Adding an email step after this write does not re-cap the queued batch; that
            # gap is bounded by the send-time buckets, which cap every email at execution
            # regardless of the audience size dispatched here.
            sends_email=hog_flow_sends_email(job.hog_flow.actions),
        ),
        # The audience snapshot the confirm check validated - the resolver dispatches from
        # this, not the live trigger, so a trigger edit racing the dispatch can't widen it.
        filters=job.filters,
        realtime_cohort=cohort_target,
    )


@receiver(post_save, sender=HogFlowBatchJob)
def handle_hog_flow_batch_job_created(sender, instance, created, **kwargs):
    if created:
        realtime_cohort = realtime_audience_cohort(instance.team.project_id, batch_job_audience_filters(instance))
        # The cohort's membership is partial until it finishes calculating, so its resolver parks until
        # the cohort's ready signal resumes it.
        wait_for_cohort = realtime_cohort is not None and not realtime_cohort_is_ready(realtime_cohort)
        if wait_for_cohort:
            HogFlowBatchJob.objects.filter(pk=instance.pk).update(status=HogFlowBatchJobState.WAITING)
            instance.status = HogFlowBatchJobState.WAITING
        try:
            dispatch_batch_job(instance, realtime_cohort, wait_for_cohort=wait_for_cohort).raise_for_status()
        except Exception as e:
            logger.exception(
                "Failed to create batch hogflow job invocation",
                batch_job_id=instance.id,
                error=str(e),
            )
            # A rejected request or one that never connected queued no resolver, so nothing would ever move the
            # run on. Any other failure may have queued one, so the run stays stoppable.
            if isinstance(e, requests.HTTPError | requests.ConnectTimeout):
                HogFlowBatchJob.objects.filter(pk=instance.pk).update(status=HogFlowBatchJobState.FAILED)
                instance.status = HogFlowBatchJobState.FAILED
            raise
        if wait_for_cohort and realtime_cohort is not None:
            # The cohort can finish between the check above and the park, and its ready signal then finds
            # no parked resolver. A resume check after the park covers that; it does nothing while the
            # cohort still calculates. A failed publish only logs, because the send is already accepted and a
            # retried request would create a second run.
            from products.workflows.backend.tasks.batch_jobs import (  # noqa: PLC0415 — the task module imports this model
                resume_batch_jobs_waiting_for_realtime_cohort,
            )

            team_id, cohort_id = realtime_cohort.team_id, realtime_cohort.pk
            transaction.on_commit(
                lambda: resume_batch_jobs_waiting_for_realtime_cohort.delay(team_id, cohort_id), robust=True
            )
