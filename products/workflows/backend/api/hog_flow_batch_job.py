import structlog
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob

logger = structlog.get_logger(__name__)


class HogFlowBatchJobSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = HogFlowBatchJob
        fields = [
            "id",
            "status",
            "hog_flow",
            "filters",
            "variables",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "filters",
            "created_at",
            "created_by",
            "updated_at",
        ]
        extra_kwargs = {
            "status": {
                "help_text": (
                    "Not currently tracked — stays at its initial value. Use the workflow logs/metrics "
                    "endpoints for run outcome."
                )
            },
            "hog_flow": {"help_text": "ID of the workflow this batch run belongs to."},
            "filters": {
                "help_text": "Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters."
            },
            "variables": {"help_text": "Variable value overrides applied to this run."},
        }

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlowBatchJob:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)


class HogFlowBatchJobCancelResponseSerializer(serializers.Serializer):
    """
    Response from the batch job cancel endpoint. Stopping is asynchronous: this call flags the
    run's audience fan-out and its in-flight child runs, and the workflow workers terminate
    them shortly after. Messages already sent are not recalled.
    """

    status = serializers.ChoiceField(
        choices=HogFlowBatchJob.State.choices,
        help_text="The batch run's status after this request. 'cancelled' once every in-flight run is flagged; "
        "a completion that raced the stop wins and is reported instead.",
    )
    marked = serializers.IntegerField(help_text="In-flight runs newly flagged for cancellation by this request.")
    remaining = serializers.IntegerField(
        help_text="In-flight runs of this batch not yet flagged. Non-zero on very large runs; call again."
    )
    done = serializers.BooleanField(help_text="True when no in-flight runs of this batch remain unflagged.")
