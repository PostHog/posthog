"""DRF serializers for founder_mode."""

from rest_framework import serializers

from products.founder_mode.backend.logic.hashing import ideation_hash
from products.founder_mode.backend.models import FounderProject


class FounderProjectSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=200,
        help_text='Founder-chosen label for the startup idea, e.g. "AI-powered HOA management".',
    )
    ideation = serializers.JSONField(
        required=False,
        help_text=(
            "Stage 1 output. Expected shape: {what, how, who, problem}. Writing here triggers "
            "the validation Celery task asynchronously."
        ),
    )
    validation = serializers.JSONField(
        read_only=True,
        help_text=(
            "Stage 2 output, server-managed. Shape: {status, current_pass, report, error, "
            "ideation_hash, started_at, completed_at|failed_at, trace_id}. Clients poll this "
            "while status is running."
        ),
    )
    gtm = serializers.JSONField(required=False, help_text="Stage 3 (go-to-market) output. Shape owned by stage 3.")
    mvp = serializers.JSONField(required=False, help_text="Stage 4 (MVP/landing page) output. Shape owned by stage 4.")
    created_by = serializers.PrimaryKeyRelatedField(
        read_only=True,
        help_text="The user who created this founder project. Set automatically on create.",
    )
    ideation_hash = serializers.SerializerMethodField(
        help_text=(
            "Stable SHA-256 of the current ideation payload. Clients compare this to "
            "`validation.ideation_hash` to detect a stale report (founder edited ideation "
            "since the last validation run)."
        ),
    )

    class Meta:
        model = FounderProject
        fields = [
            "id",
            "name",
            "ideation",
            "ideation_hash",
            "validation",
            "gtm",
            "mvp",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "ideation_hash", "validation", "created_by", "created_at", "updated_at"]

    def get_ideation_hash(self, obj: FounderProject) -> str:
        return ideation_hash(obj.ideation)
