import structlog
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.workflows.backend.facade.enums import HogFlowBatchJobState

logger = structlog.get_logger(__name__)

BATCH_RUN_STATUS_HELP_TEXT = (
    "Status of the batch run. waiting: the audience's cohort is still calculating. queued and active: the run "
    "is enrolling its audience. completed: the whole audience was enrolled. When every enrolled person's run "
    "has ended, or a day after the run completed, PostHog checks for errored sends. A completed run stays "
    "completed when no send errored, becomes "
    "partially_failed when some sends errored, and becomes failed when every send errored. failed also means "
    "the run could not enroll its audience. cancelled: someone stopped the run. A send errors when its step "
    "throws, for example on a template that does not render. Provider failures such as bounces are not errored "
    "sends; read them from the run's metrics."
)


class HogFlowBatchJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="ID of the batch run.")
    status = serializers.ChoiceField(
        choices=HogFlowBatchJobState.choices,
        required=False,
        help_text=BATCH_RUN_STATUS_HELP_TEXT,
    )
    hog_flow = serializers.UUIDField(source="hog_flow_id", help_text="ID of the workflow this batch run belongs to.")
    filters = serializers.JSONField(
        read_only=True,
        help_text="Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters.",
    )
    variables = serializers.JSONField(required=False, help_text="Variable value overrides applied to this run.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the batch run was created.")
    created_by = UserBasicSerializer(read_only=True, help_text="User who started the batch run.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the batch run was last updated.")

    def validate_status(self, value: str) -> str:
        # A waiting run is one PostHog has not dispatched yet, and stopping it skips the workers.
        if value == HogFlowBatchJobState.WAITING:
            raise serializers.ValidationError(
                "PostHog sets 'waiting' itself while the audience's cohort calculates. Leave the status out."
            )
        return value


class HogFlowBatchJobCancelResponseSerializer(serializers.Serializer):
    """
    Response from the batch job cancel endpoint. Stopping is asynchronous: this call flags the
    run's audience fan-out and its in-flight child runs, and the workflow workers terminate
    them shortly after. Messages already sent are not recalled.
    """

    status = serializers.ChoiceField(
        choices=HogFlowBatchJobState.choices,
        help_text="The batch run's status after this request. 'cancelled' once every in-flight run is flagged; "
        "a completion that raced the stop wins and is reported instead.",
    )
    marked = serializers.IntegerField(help_text="In-flight runs newly flagged for cancellation by this request.")
    remaining = serializers.IntegerField(
        help_text="In-flight runs of this batch not yet flagged. Non-zero on very large runs; call again."
    )
    done = serializers.BooleanField(help_text="True when no in-flight runs of this batch remain unflagged.")
