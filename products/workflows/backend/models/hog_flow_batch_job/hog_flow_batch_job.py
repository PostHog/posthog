from uuid import UUID

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

import structlog

from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.plugins.plugin_server_api import create_batch_hog_flow_job_invocation

from products.workflows.backend.utils.batch_trigger_limit import get_hogflow_batch_trigger_limit, hog_flow_sends_email

logger = structlog.get_logger(__name__)


class HogFlowBatchJob(RootTeamMixin, UUIDTModel):
    """
    Stores the status and other meta information for a batch of HogFlow jobs (typically used for a broadcast)
    """

    class Meta:
        indexes = [
            models.Index(fields=["team"]),
        ]

    class State(models.TextChoices):
        WAITING = "waiting"
        QUEUED = "queued"
        ACTIVE = "active"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        FAILED = "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING)
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.DO_NOTHING)
    variables = models.JSONField(default=dict)
    filters = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=State, default=State.QUEUED)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.DO_NOTHING, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"HogFlow batch run {self.id}"


NON_TERMINAL_BATCH_JOB_STATES = (
    HogFlowBatchJob.State.WAITING,
    HogFlowBatchJob.State.QUEUED,
    HogFlowBatchJob.State.ACTIVE,
)


def _mark_dispatch_failed(batch_job: HogFlowBatchJob) -> None:
    updated = HogFlowBatchJob.objects.filter(id=batch_job.id, status=HogFlowBatchJob.State.QUEUED).update(
        status=HogFlowBatchJob.State.FAILED, updated_at=timezone.now()
    )
    if updated:
        batch_job.status = HogFlowBatchJob.State.FAILED


def cancel_batch_jobs_for_inactive_flow(hog_flow_id: UUID) -> int:
    return HogFlowBatchJob.objects.filter(hog_flow_id=hog_flow_id, status__in=NON_TERMINAL_BATCH_JOB_STATES).update(
        status=HogFlowBatchJob.State.CANCELLED, updated_at=timezone.now()
    )


@receiver(post_save, sender=HogFlowBatchJob)
def handle_hog_flow_batch_job_created(sender, instance, created, **kwargs):
    if created:
        try:
            response = create_batch_hog_flow_job_invocation(
                team_id=instance.team.id,
                hog_flow_id=instance.hog_flow.id,
                batch_job_id=instance.id,
                max_audience_size=get_hogflow_batch_trigger_limit(
                    instance.team.id,
                    # The dispatch runs the live config, so the live actions decide the channel.
                    # Adding an email step after this write does not re-cap the queued batch; that
                    # gap is bounded by the send-time buckets, which cap every email at execution
                    # regardless of the audience size dispatched here.
                    sends_email=hog_flow_sends_email(instance.hog_flow.actions),
                ),
                # The audience snapshot the confirm check validated - the resolver dispatches from
                # this, not the live trigger, so a trigger edit racing the dispatch can't widen it.
                filters=instance.filters,
            )
        except Exception as e:
            _mark_dispatch_failed(instance)
            logger.exception(
                "Failed to create batch hogflow job invocation",
                batch_job_id=instance.id,
                error=str(e),
            )
            raise

        if not response.ok:
            _mark_dispatch_failed(instance)
            logger.error(
                "Batch hogflow job invocation was rejected",
                batch_job_id=instance.id,
                status_code=response.status_code,
            )
