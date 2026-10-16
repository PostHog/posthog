from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.plugins.plugin_server_api import create_batch_hog_flow_job_invocation

from products.workflows.backend.facade.enums import HogFlowBatchJobState
from products.workflows.backend.services.batch_audience_cohorts import (
    realtime_audience_cohort,
    realtime_cohort_is_ready,
)
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


@receiver(post_save, sender=HogFlowBatchJob)
def handle_hog_flow_batch_job_created(sender, instance, created, **kwargs):
    if created:
        realtime_cohort = realtime_audience_cohort(instance.team.project_id, batch_job_audience_filters(instance))
        if realtime_cohort is not None and not realtime_cohort_is_ready(realtime_cohort):
            # An edit to the cohort since the save cleared its readiness. Its membership is partial until
            # it finishes calculating again, so the run fails instead of sending to the wrong people.
            logger.warning(
                "Batch run audience realtime cohort isn't ready", batch_job_id=instance.id, cohort_id=realtime_cohort.pk
            )
            HogFlowBatchJob.objects.filter(pk=instance.pk).update(status=HogFlowBatchJobState.FAILED)
            instance.status = HogFlowBatchJobState.FAILED
            return
        try:
            create_batch_hog_flow_job_invocation(
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
                realtime_cohort=(
                    {"id": realtime_cohort.pk, "team_id": realtime_cohort.team_id} if realtime_cohort else None
                ),
            )
        except Exception as e:
            logger.exception(
                "Failed to create batch hogflow job invocation",
                batch_job_id=instance.id,
                error=str(e),
            )
            raise
