"""DRF serializers for stamphog."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.integration import Integration

from ..facade.enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewVerdict
from ..models import DigestChannel, DigestRun, ReviewRun, StamphogRepoConfig


@extend_schema_field(OpenApiTypes.OBJECT)
class _GateResultField(serializers.JSONField):
    pass


@extend_schema_field(OpenApiTypes.OBJECT)
class _ReviewOutputField(serializers.JSONField):
    pass


@extend_schema_field(OpenApiTypes.OBJECT)
class _DigestSummaryField(serializers.JSONField):
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
            "digest_enabled",
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
            "digest_enabled": {
                "required": False,
                "help_text": "Whether merged PRs on this repo are captured for the daily Slack digest.",
            },
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


class DigestChannelSerializer(serializers.ModelSerializer):
    resolution_source = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in ChannelResolutionSource],
        read_only=True,
        help_text=(
            "How this row was created: 'manual' (via this API), 'slack_name_match' (auto-provisioned "
            "because the workspace has a channel named exactly like the audience_key), or "
            "'owners_contact' (reserved for the future owners.yaml contact.slack step, not implemented yet)."
        ),
    )

    class Meta:
        model = DigestChannel
        fields = [
            "id",
            "audience_key",
            "slack_integration_id",
            "slack_channel_id",
            "slack_channel_name",
            "resolution_source",
            "enabled",
            "last_digest_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "last_digest_at", "created_at", "updated_at"]
        extra_kwargs = {
            "audience_key": {"help_text": "Opaque digest bucket this channel receives, e.g. 'repo:PostHog/posthog'."},
            "slack_integration_id": {
                "help_text": "ID of the team's Slack integration used to post the digest.",
            },
            "slack_channel_id": {
                "help_text": "Slack channel ID to post the digest to, e.g. 'C012AB3CD'.",
            },
            "slack_channel_name": {
                "required": False,
                "help_text": "Human-readable Slack channel name, for display only.",
            },
            "enabled": {"help_text": "Whether this channel is included in the daily digest fan-out."},
        }

    def validate_slack_integration_id(self, value: int) -> int:
        # The integration must belong to the requesting team and be a Slack integration — otherwise a
        # team could point a digest at another team's Slack workspace.
        team_id = self.context["team_id"]
        exists = Integration.objects.filter(id=value, team_id=team_id, kind="slack").exists()
        if not exists:
            raise serializers.ValidationError("No Slack integration with this ID exists for this team.")
        return value


class DigestRunSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in DigestRunStatus],
        read_only=True,
        help_text="Current state of the digest run (pending, completed, failed).",
    )
    summary = _DigestSummaryField(
        read_only=True,
        help_text="Rendered digest summary (intro plus per-PR one-liners) posted to Slack.",
    )

    class Meta:
        model = DigestRun
        fields = [
            "id",
            "digest_channel",
            "status",
            "pr_count",
            "summary",
            "slack_message_ts",
            "error",
            "created_at",
            "posted_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "digest_channel": {"help_text": "ID of the digest channel this run belongs to."},
            "pr_count": {"help_text": "Number of merged PRs included in the posted digest."},
            "slack_message_ts": {"help_text": "Slack message timestamp of the posted digest, if posted."},
            "error": {"help_text": "Error message if the run failed, blank otherwise."},
            "created_at": {"help_text": "When the digest run was created."},
            "posted_at": {"help_text": "When the digest was posted to Slack, if it was."},
        }
