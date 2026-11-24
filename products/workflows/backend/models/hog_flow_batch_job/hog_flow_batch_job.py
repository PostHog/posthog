from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import requests
import structlog

from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.plugins.plugin_server_api import create_batch_hog_flow_job_invocation

from products.workflows.backend.facade.enums import HogFlowBatchJobAudienceStatus, HogFlowBatchJobState
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.batch_audience_cohorts import (
    realtime_audience_cohort,
    realtime_cohort_is_ready,
)
from products.workflows.backend.utils.audience_snapshot import AUDIENCE_SNAPSHOT_WAIT_LIMIT, use_audience_snapshot
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
            models.Index(fields=["hog_flow", "-created_at"], name="hogflowbatchjob_flow_recent"),
        ]

    State = HogFlowBatchJobState

    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING, related_name="+")
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.DO_NOTHING)
    variables = models.JSONField(default=dict)
    filters = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED.value)
    # Set only on runs that resolve their whole audience once before paging; null on runs that page the live query.
    audience_status = models.CharField(
        max_length=20, choices=HogFlowBatchJobAudienceStatus.choices, null=True, blank=True
    )
    audience_size = models.IntegerField(null=True, blank=True)
    audience_error = models.TextField(null=True, blank=True)
    # The audience cap dispatch sent the resolver, which locks a raising rate limit while the run may still send.
    max_audience_size = models.IntegerField(null=True, blank=True)

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


def batch_job_audience_type(job: HogFlowBatchJob) -> str | None:
    snapshot_type = (job.filters or {}).get("audience_type")
    return snapshot_type or ((job.hog_flow.trigger or {}).get("filters") or {}).get("audience_type")


def dispatch_batch_job(
    job: HogFlowBatchJob,
    realtime_cohort: "Cohort | None",
    *,
    wait_for_cohort: bool = False,
    snapshot_audience: bool = False,
) -> "requests.Response":
    cohort_target: dict | None = None
    if realtime_cohort is not None:
        cohort_target = {"id": realtime_cohort.pk, "team_id": realtime_cohort.team_id}
        if wait_for_cohort:
            # The resolver parks until a resume wakes it, and fails the run at this instant otherwise.
            cohort_target["wait_until"] = (job.created_at + REALTIME_COHORT_WAIT_LIMIT).isoformat()
    error: Exception | None = None
    # The resolver is enqueued under the workflow's row lock, so a rate limit edit's locked re-check either
    # lands before the cap is read here or finds the cap recorded and the resolver already in flight.
    with transaction.atomic():
        hog_flow = HogFlow.objects.select_for_update().get(pk=job.hog_flow_id)
        max_audience_size = get_hogflow_batch_trigger_limit(
            job.team.id,
            # The dispatch runs the live config, so the live actions decide the channel.
            # Adding an email step after this write does not re-cap the queued batch; that
            # gap is bounded by the send-time buckets, which cap every email at execution
            # regardless of the audience size dispatched here.
            sends_email=hog_flow_sends_email(hog_flow.actions),
            email_rate_limit=hog_flow.email_sending_rate_limit,
        )
        HogFlowBatchJob.objects.filter(pk=job.pk).update(max_audience_size=max_audience_size)
        try:
            response = create_batch_hog_flow_job_invocation(
                team_id=job.team.id,
                hog_flow_id=job.hog_flow.id,
                batch_job_id=job.id,
                max_audience_size=max_audience_size,
                # The audience snapshot the confirm check validated - the resolver dispatches from
                # this, not the live trigger, so a trigger edit racing the dispatch can't widen it.
                filters=job.filters,
                realtime_cohort=cohort_target,
                # The resolver pages a stored audience instead of the live query, and fails the run at this instant
                # if the audience never resolves.
                audience_snapshot=(
                    {"wait_until": (job.created_at + AUDIENCE_SNAPSHOT_WAIT_LIMIT).isoformat()}
                    if snapshot_audience
                    else None
                ),
            )
        except Exception as e:
            # Commit the recorded cap anyway: a call that failed after sending may still have queued the resolver.
            error = e
    if error is not None:
        raise error
    return response


def dispatch_queued_no_resolver(error: BaseException) -> bool:
    """A rejected dispatch, or one that never connected, queued no resolver. Any other failure may have queued one."""
    return isinstance(error, requests.HTTPError | requests.ConnectTimeout)


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
        snapshot_audience = (
            realtime_cohort is None
            and batch_job_audience_type(instance) != "accounts"
            and use_audience_snapshot(instance.team)
        )
        try:
            dispatch_batch_job(
                instance, realtime_cohort, wait_for_cohort=wait_for_cohort, snapshot_audience=snapshot_audience
            ).raise_for_status()
        except Exception as e:
            logger.exception(
                "Failed to create batch hogflow job invocation",
                batch_job_id=instance.id,
                error=str(e),
            )
            # Nothing would ever move such a run on; any other failure leaves it stoppable.
            if dispatch_queued_no_resolver(e):
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
