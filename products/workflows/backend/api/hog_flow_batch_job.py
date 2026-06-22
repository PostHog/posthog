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
            "skip_reason",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "skip_reason",
            "created_at",
            "created_by",
            "updated_at",
        ]
        extra_kwargs = {
            "status": {
                "help_text": (
                    "Not currently tracked — stays at its initial value, except for 'skipped' rows which "
                    "represent runs that never executed (see skip_reason). Use the workflow logs/metrics "
                    "endpoints for run outcome."
                )
            },
            "hog_flow": {"help_text": "ID of the workflow this batch run belongs to."},
            "filters": {
                "help_text": "Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters."
            },
            "variables": {"help_text": "Variable value overrides applied to this run."},
            "skip_reason": {
                "help_text": (
                    "Populated only when status is 'skipped'. Object describing why the run was skipped — "
                    "currently {'reason': 'audience_over_limit', 'affected': int, 'limit': int}."
                ),
            },
        }

    def create(self, validated_data: dict, *args, **kwargs) -> HogFlowBatchJob:
        request = self.context["request"]
        team_id = self.context["team_id"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = team_id

        return super().create(validated_data=validated_data)
