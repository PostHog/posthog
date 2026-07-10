"""DRF serializers for stamphog."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.enums import ReviewRunStatus, ReviewVerdict
from ..models import ReviewRun, StamphogRepoConfig


@extend_schema_field(OpenApiTypes.OBJECT)
class _GateResultField(serializers.JSONField):
    pass


@extend_schema_field(OpenApiTypes.OBJECT)
class _ReviewOutputField(serializers.JSONField):
    pass


class StamphogRepoConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = StamphogRepoConfig
        fields = [
            "id",
            "provider",
            "repository",
            "enabled",
            "installation_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "provider": {
                "required": False,
                "help_text": "SCM provider this config talks to. Defaults to 'github'.",
            },
            "repository": {"help_text": "Repository full name, e.g. 'PostHog/posthog'."},
            "enabled": {"help_text": "Whether stamphog actively reviews pull requests for this repo."},
            "installation_id": {"help_text": "Provider app installation ID that authorizes API calls for this repo."},
        }


class ReviewRunSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(
        source="repo_config.repository",
        read_only=True,
        help_text="Full name of the repository this review run belongs to.",
    )
    status = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in ReviewRunStatus],
        read_only=True,
        help_text="Current stage of the review run's lifecycle.",
    )
    verdict = serializers.ChoiceField(
        choices=[(v.value, v.name) for v in ReviewVerdict],
        read_only=True,
        help_text="Final verdict reached by the reviewer, if any.",
    )
    gate_result = _GateResultField(
        read_only=True,
        help_text="Deterministic gate check outcome (pass/fail, tier, reason) computed before the reviewer runs.",
    )
    output = _ReviewOutputField(
        read_only=True,
        help_text="Structured reviewer output (reasoning, showstoppers, posted comment/review body).",
    )

    class Meta:
        model = ReviewRun
        fields = [
            "id",
            "repository",
            "pr_number",
            "pr_url",
            "head_sha",
            "head_branch",
            "delivery_id",
            "status",
            "verdict",
            "gate_result",
            "output",
            "error",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "pr_number": {"help_text": "Pull request number on GitHub."},
            "pr_url": {"help_text": "Full URL to the pull request on GitHub."},
            "head_sha": {"help_text": "Commit SHA of the PR head at the time this run started."},
            "head_branch": {"help_text": "Branch name of the PR head at the time this run started."},
            "delivery_id": {"help_text": "GitHub webhook delivery ID that triggered this run, used for deduplication."},
            "error": {"help_text": "Error message if the run failed, blank otherwise."},
            "created_at": {"help_text": "When the review run was created."},
            "updated_at": {"help_text": "When the review run was last updated."},
            "completed_at": {"help_text": "When the review run reached a terminal state, if it has."},
        }
