"""DRF serializers for stamphog."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from posthog.models.integration import Integration

from ..facade.enums import ChannelResolutionSource, DigestRunStatus, ReviewRunStatus, ReviewVerdict
from ..models import DigestChannel, DigestRun, PullRequest, ReviewRun, StamphogRepoConfig


class _GateResultSummarySerializer(serializers.Serializer):
    """Allowlisted, content-free slice of ``ReviewRun.gate_result``.

    The raw gate blob nests ``gates``, ``classification``, and ``policy`` sub-objects that carry
    repository content — changed-file paths (``safe_migration_files``, ``invalid_folder_files``),
    manifest gate messages, and declared ``policy.scopes`` — which a project member without repo
    access must not read. Only the terminal decision is exposed.
    """

    gate_blocked = serializers.BooleanField(
        read_only=True,
        required=False,
        help_text="Whether the deterministic gates blocked auto-review before the reviewer ran.",
    )
    final_verdict = serializers.CharField(
        read_only=True,
        required=False,
        help_text="The engine's raw final-verdict token, if the run reached a verdict.",
    )


class _ReviewOutputSummarySerializer(serializers.Serializer):
    """Allowlisted, non-sensitive slice of ``ReviewRun.output``.

    The raw ``output`` blob also holds the reviewer's stdout, the full PR payload, changed-file patches,
    and default-branch policy file contents — repository content a project member without repo access
    must never read over the API. Only these derived, content-free fields are exposed.
    """

    stamphog_version = serializers.CharField(
        read_only=True,
        required=False,
        help_text="Version of the stamphog engine that produced this review, if it reported one.",
    )
    reviewer_exit_code = serializers.IntegerField(
        read_only=True,
        required=False,
        help_text="Exit code of the reviewer process in the sandbox, if the run reached the sandbox stage.",
    )


class StamphogRepoConfigSerializer(serializers.ModelSerializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # provider + repository are the config's identity: they resolve inbound webhooks and anchor
        # every PullRequest/ReviewRun FK. Editing them on an existing row would reroute that history to a
        # different repo and stop the original repo's webhooks from resolving, so they're create-only.
        # self.instance is set only for updates (schema generation and creates leave it None).
        if self.instance is not None:
            fields["provider"].read_only = True
            fields["repository"].read_only = True
        return fields

    def validate_trigger_label(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Trigger label cannot be blank.")
        return value

    class Meta:
        model = StamphogRepoConfig
        fields = [
            "id",
            "provider",
            "repository",
            "enabled",
            "installation_id",
            "digest_enabled",
            "review_mode",
            "trigger_label",
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
            # Read-only on purpose: an installation id may only ever be set by the verified
            # sync_installation flow, which proves the caller owns the installation before binding it.
            # A client-supplied value on the plain create/update path is ignored, so a manually created
            # config carries no installation and simply won't resolve webhooks until synced.
            "installation_id": {
                "read_only": True,
                "help_text": (
                    "Provider app installation ID that authorizes API calls for this repo. Set only by the "
                    "verified sync_installation flow; ignored on direct writes."
                ),
            },
            "digest_enabled": {
                "required": False,
                "help_text": "Whether merged PRs on this repo are captured for the daily Slack digest.",
            },
            "review_mode": {
                "required": False,
                "help_text": (
                    "When reviews run: 'all' reviews every pull request (the default); 'label' reviews "
                    "only pull requests carrying the trigger label, mirroring the Action's opt-in flow."
                ),
            },
            "trigger_label": {
                "required": False,
                "help_text": (
                    "Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."
                ),
            },
        }


class StamphogInstallInfoSerializer(serializers.Serializer):
    """Static info the frontend needs to render the 'Connect a repository' button."""

    app_slug = serializers.CharField(
        read_only=True,
        help_text="URL-friendly slug of the dedicated Stamphog GitHub App, or blank if unconfigured.",
    )
    install_url = serializers.CharField(
        read_only=True,
        help_text=(
            "GitHub install URL (github.com/apps/<slug>/installations/new) the user opens to install the "
            "App, or blank if the App slug is unconfigured."
        ),
    )


class StamphogSyncInstallationRequestSerializer(serializers.Serializer):
    """Request body for binding a completed GitHub App installation to the current team.

    Requires both the ``installation_id`` and the user-to-server OAuth ``code`` from the post-install
    redirect: the code proves the caller actually owns the installation, without which any caller could
    bind another org's installation to their own team.
    """

    installation_id = serializers.CharField(
        help_text="GitHub App installation ID returned on the post-install Setup URL redirect.",
    )
    code = serializers.CharField(
        help_text=(
            "GitHub user-to-server OAuth code from the post-install redirect (present when the App has "
            "'Request user authorization during installation' enabled). Exchanged server-side to prove "
            "the caller owns the installation before its repos are bound."
        ),
    )
    state = serializers.CharField(
        help_text=(
            "Signed state token minted by install_info and round-tripped through GitHub's install "
            "redirect. Binds the callback to the team and user that started the flow, so a stolen "
            "installation_id + code can't be replayed against another team's session."
        ),
    )


class StamphogSyncInstallationResponseSerializer(serializers.Serializer):
    """Result of syncing an installation: rows created/kept for this team, plus conflicting repos skipped."""

    synced = StamphogRepoConfigSerializer(
        many=True,
        read_only=True,
        help_text="Repo configs now bound to this team for the installation (created this call or already present).",
    )
    skipped = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Repository full names skipped because another team already owns them under this installation.",
    )


@extend_schema_serializer(component_name="StamphogPullRequest")
class PullRequestSerializer(serializers.ModelSerializer):
    repository = serializers.CharField(
        source="repo_config.repository",
        read_only=True,
        help_text="Full name of the repository this pull request belongs to.",
    )
    merged = serializers.SerializerMethodField(
        help_text="Whether this pull request has merged (merged_at is set).",
    )

    class Meta:
        model = PullRequest
        fields = [
            "id",
            "repository",
            "pr_number",
            "title",
            "author_login",
            "pr_url",
            "head_branch",
            "merged",
            "merged_at",
            "merge_commit_sha",
            "additions",
            "deletions",
            "changed_files",
            "audience_key",
            "digest_run",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "pr_number": {"help_text": "Pull request number on GitHub."},
            "title": {"help_text": "Pull request title, refreshed on every relevant webhook delivery."},
            "author_login": {"help_text": "GitHub login of the pull request author."},
            "pr_url": {"help_text": "Full URL to the pull request on GitHub."},
            "head_branch": {"help_text": "Branch name of the PR head."},
            "merged_at": {"help_text": "When the pull request merged, null if it hasn't."},
            "merge_commit_sha": {"help_text": "Merge commit SHA, blank until the pull request merges."},
            "additions": {"help_text": "Lines added, recorded when the pull request merges."},
            "deletions": {"help_text": "Lines deleted, recorded when the pull request merges."},
            "changed_files": {"help_text": "Files changed, recorded when the pull request merges."},
            "audience_key": {
                "help_text": "Digest bucket this merged PR belongs to; blank unless it was digest-eligible."
            },
            "digest_run": {"help_text": "ID of the digest run that reported this merged PR, if any."},
            "created_at": {"help_text": "When this pull request was first captured."},
            "updated_at": {"help_text": "When this pull request was last updated."},
        }

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_merged(self, obj: PullRequest) -> bool:
        return obj.merged_at is not None


class ReviewRunSerializer(serializers.ModelSerializer):
    pull_request = serializers.UUIDField(
        source="pull_request_id",
        read_only=True,
        help_text="ID of the pull request this review run belongs to.",
    )
    repository = serializers.CharField(
        source="pull_request.repo_config.repository",
        read_only=True,
        help_text="Full name of the repository this review run belongs to.",
    )
    pr_number = serializers.IntegerField(
        source="pull_request.pr_number",
        read_only=True,
        help_text="Pull request number on GitHub.",
    )
    pr_url = serializers.CharField(
        source="pull_request.pr_url",
        read_only=True,
        help_text="Full URL to the pull request on GitHub.",
    )
    head_branch = serializers.CharField(
        source="pull_request.head_branch",
        read_only=True,
        help_text="Branch name of the PR head.",
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
    gate_result = serializers.SerializerMethodField(
        help_text=(
            "Allowlisted deterministic gate outcome (gate_blocked, final_verdict). The nested gate, "
            "classification, and policy sub-objects are excluded — they carry changed-file paths and "
            "policy scopes, repository content a project member without repo access must not read."
        ),
    )
    output = serializers.SerializerMethodField(
        help_text=(
            "Allowlisted, non-sensitive subset of the reviewer output blob (stamphog version, reviewer "
            "exit code). The raw reviewer stdout, PR payload, changed-file patches, and policy file "
            "contents are deliberately excluded — they carry repository content a project member without "
            "repo access must not read."
        ),
    )

    @extend_schema_field(_ReviewOutputSummarySerializer)
    def get_output(self, obj: ReviewRun) -> dict[str, object]:
        # Explicit allowlist: never echo reviewer_raw / pr / files / policy_files out of the API.
        raw = obj.output or {}
        summary: dict[str, object] = {}
        if "stamphog_version" in raw:
            summary["stamphog_version"] = raw["stamphog_version"]
        if "reviewer_exit_code" in raw:
            summary["reviewer_exit_code"] = raw["reviewer_exit_code"]
        return summary

    @extend_schema_field(_GateResultSummarySerializer)
    def get_gate_result(self, obj: ReviewRun) -> dict[str, object]:
        # Explicit allowlist: never echo the gates / classification / policy sub-objects, which carry
        # changed-file paths and policy scopes.
        raw = obj.gate_result or {}
        summary: dict[str, object] = {}
        if "gate_blocked" in raw:
            summary["gate_blocked"] = raw["gate_blocked"]
        if "final_verdict" in raw:
            summary["final_verdict"] = raw["final_verdict"]
        return summary

    class Meta:
        model = ReviewRun
        fields = [
            "id",
            "pull_request",
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
            "head_sha": {"help_text": "Commit SHA of the PR head at the time this run started."},
            "delivery_id": {"help_text": "GitHub webhook delivery ID that triggered this run, used for deduplication."},
            "error": {"help_text": "Error message if the run failed, blank otherwise."},
            "created_at": {"help_text": "When the review run was created."},
            "updated_at": {"help_text": "When the review run was last updated."},
            "completed_at": {"help_text": "When the review run reached a terminal state, if it has."},
        }


class DigestChannelSerializer(serializers.ModelSerializer):
    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        # audience_key is the bucket this channel is bound to. Editing it on an existing row re-points
        # the channel at a different audience — and can effectively re-open an audience a human opted out
        # of, since the disabled tombstone row keying off the old audience_key would no longer match.
        # Create-only, same pattern as the repo config's provider/repository identity fields.
        # self.instance is set only for updates (schema generation and creates leave it None).
        if self.instance is not None:
            fields["audience_key"].read_only = True
        return fields

    resolution_source = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in ChannelResolutionSource],
        read_only=True,
        help_text=(
            "How this row was created: 'manual' (via this API), 'slack_name_match' (auto-provisioned "
            "because the workspace has a channel named exactly like the audience_key), "
            "'stamphog_config' (auto-provisioned from the channel the repo declared under 'digest:' in "
            ".stamphog/policy.yml), "
            "or 'owners_contact' (reserved for the future owners.yaml contact.slack step, not implemented yet)."
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
            "audience_key": {
                "help_text": (
                    "Opaque digest bucket this channel receives, e.g. 'repo:PostHog/posthog'. Immutable "
                    "after creation — it anchors the audience and its opt-out tombstone."
                )
            },
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
    # The rendered summary is deliberately NOT exposed here: it's generated from each PR's body_excerpt,
    # so it reproduces repository content a project member without GitHub repo access must not read. It
    # lives only in the Slack post (whose audience already has channel access).

    class Meta:
        model = DigestRun
        fields = [
            "id",
            "digest_channel",
            "status",
            "pr_count",
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
