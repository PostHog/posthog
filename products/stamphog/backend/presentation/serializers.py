"""DRF serializers for stamphog.

Every serializer here reads and writes facade contracts, never ORM models — the presentation
layer reaches product data only through ``facade.api``. Field-level help text is the source of
the generated OpenAPI schema, so it stays on the serializer rather than moving to the contract.
"""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade import contracts
from ..facade.enums import (
    ChannelResolutionSource,
    DigestRunStatus,
    ReviewMode,
    ReviewRunStatus,
    ReviewTrigger,
    ReviewVerdict,
)


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
    must never read. Only these derived, content-free fields are exposed.
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


@extend_schema_serializer(component_name="StamphogRepoConfig")
class StamphogRepoConfigSerializer(DataclassSerializer):
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

    review_mode = serializers.ChoiceField(
        choices=[(m.value, m.value) for m in ReviewMode],
        read_only=True,
        help_text=(
            "When reviews run: 'all' reviews every pull request (the default); 'label' reviews "
            "only pull requests carrying the trigger label, mirroring the Action's opt-in flow."
        ),
    )

    class Meta:
        dataclass = contracts.RepoConfigDTO
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
                "help_text": (
                    "Whether merged PRs on this repo are captured for the daily Slack digest. Requires "
                    "'enabled', since the digest reports what stamphog approved."
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
            "App, or blank if the App slug is unconfigured. Used for the genuinely-not-installed case; the "
            "primary 'Connect' button uses authorize_url instead."
        ),
    )
    authorize_url = serializers.CharField(
        read_only=True,
        help_text=(
            "GitHub authorize URL (github.com/login/oauth/authorize) the 'Connect' button opens. "
            "Authorize-first: an already-installed user is redirected straight back with an OAuth code (no "
            "installation_id), and sync_installation then discovers their installations server-side. Blank "
            "if the App client id is unconfigured."
        ),
    )


class StamphogSyncInstallationRequestSerializer(serializers.Serializer):
    """Request body for binding a GitHub App installation to the current team.

    Always requires the user-to-server OAuth ``code`` (the ownership proof) and the ``state`` token.
    ``installation_id`` is optional: when present (the fresh-install redirect) exactly that installation
    is verified and synced; when absent or blank (the authorize-first redirect) the caller's accessible
    installations are discovered server-side from the code, so the client never has to supply a
    forgeable id.
    """

    installation_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "GitHub App installation ID from the fresh-install Setup URL redirect. Optional: absent or "
            "blank means discover the caller's installations from the OAuth code instead (authorize-first "
            "flow). The id is not trusted on its own — ownership is always proven via the code."
        ),
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


class StamphogDiscoveredInstallationSerializer(serializers.Serializer):
    """One installation of the App the authorizing user can reach, offered for an explicit pick."""

    id = serializers.CharField(read_only=True, help_text="GitHub installation id, as a string.")
    account_login = serializers.CharField(
        read_only=True, help_text="Login of the org or user account the installation lives on."
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
    app_not_installed = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True only on the discovery path (no installation_id) when the caller can reach no installation "
            "of this App — it isn't installed anywhere they can see. The frontend should route the user to "
            "the GitHub install page (install_url). Always false on the explicit installation_id path."
        ),
    )
    installations = StamphogDiscoveredInstallationSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Populated only on the discovery path when the caller can reach MORE than one installation of "
            "this App: nothing was bound, and the user must pick which installation to connect. The "
            "frontend re-runs the authorize flow and calls back with the chosen installation_id, which the "
            "explicit path verifies. Empty whenever a bind happened (or nothing was found)."
        ),
    )


@extend_schema_serializer(component_name="StamphogPullRequest")
class PullRequestSerializer(DataclassSerializer):
    repository = serializers.CharField(
        read_only=True,
        help_text="Full name of the repository this pull request belongs to.",
    )
    merged = serializers.SerializerMethodField(
        help_text="Whether this pull request has merged (merged_at is set).",
    )
    merged_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the pull request merged, null if it hasn't.",
    )

    class Meta:
        dataclass = contracts.PullRequestDTO
        # body_excerpt is deliberately absent: it reproduces pull request body text, repository
        # content a project member without GitHub repo access must not read over the API.
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
            "created_at",
            "updated_at",
        ]
        # Only the fields NOT declared above (see ReviewRunSerializer).
        read_only_fields = [
            "id",
            "pr_number",
            "title",
            "author_login",
            "pr_url",
            "head_branch",
            "merge_commit_sha",
            "additions",
            "deletions",
            "changed_files",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "pr_number": {"help_text": "Pull request number on GitHub."},
            "title": {"help_text": "Pull request title, refreshed on every relevant webhook delivery."},
            "author_login": {"help_text": "GitHub login of the pull request author."},
            "pr_url": {"help_text": "Full URL to the pull request on GitHub."},
            "head_branch": {"help_text": "Branch name of the PR head."},
            "merge_commit_sha": {"help_text": "Merge commit SHA, blank until the pull request merges."},
            "additions": {"help_text": "Lines added, recorded when the pull request merges."},
            "deletions": {"help_text": "Lines deleted, recorded when the pull request merges."},
            "changed_files": {"help_text": "Files changed, recorded when the pull request merges."},
            "created_at": {"help_text": "When this pull request was first captured."},
            "updated_at": {"help_text": "When this pull request was last updated."},
        }

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_merged(self, obj: contracts.PullRequestDTO) -> bool:
        return obj.merged_at is not None


@extend_schema_serializer(component_name="ReviewRun")
class ReviewRunSerializer(DataclassSerializer):
    pull_request = serializers.UUIDField(
        source="pull_request_id",
        read_only=True,
        help_text="ID of the pull request this review run belongs to.",
    )
    repository = serializers.CharField(
        read_only=True,
        help_text="Full name of the repository this review run belongs to.",
    )
    pr_number = serializers.IntegerField(
        read_only=True,
        help_text="Pull request number on GitHub.",
    )
    pr_url = serializers.CharField(
        read_only=True,
        help_text="Full URL to the pull request on GitHub.",
    )
    title = serializers.CharField(
        read_only=True,
        help_text="Pull request title as of the last webhook delivery applied.",
    )
    author_login = serializers.CharField(
        read_only=True,
        help_text="GitHub login of the pull request author.",
    )
    head_branch = serializers.CharField(
        read_only=True,
        help_text="Branch name of the PR head.",
    )
    trigger = serializers.ChoiceField(
        choices=[(t.value, t.name) for t in ReviewTrigger],
        read_only=True,
        help_text="What caused this run to exist: self-driving inbox provenance, the repo's trigger label, or the repo reviewing every PR event.",
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
    delivery_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="GitHub webhook delivery ID that triggered this run, used for deduplication.",
    )
    completed_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the review run reached a terminal state, if it has.",
    )
    posted_review_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the GitHub review this run posted, null if it never posted one.",
    )
    verdict_posted_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When this run's verdict reached GitHub, null if it never did.",
    )
    approval_dismissed_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When this run's GitHub approval was retracted because the head moved, null if it wasn't.",
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
    def get_output(self, obj: contracts.ReviewRunDTO) -> dict[str, object]:
        # Explicit allowlist: never echo reviewer_raw / pr / files / policy_files out of the API.
        raw = obj.output or {}
        summary: dict[str, object] = {}
        if "stamphog_version" in raw:
            summary["stamphog_version"] = raw["stamphog_version"]
        if "reviewer_exit_code" in raw:
            summary["reviewer_exit_code"] = raw["reviewer_exit_code"]
        return summary

    @extend_schema_field(_GateResultSummarySerializer)
    def get_gate_result(self, obj: contracts.ReviewRunDTO) -> dict[str, object]:
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
        dataclass = contracts.ReviewRunDTO
        fields = [
            "id",
            "pull_request",
            "repository",
            "pr_number",
            "pr_url",
            "title",
            "author_login",
            "head_sha",
            "head_branch",
            "delivery_id",
            "trigger",
            "status",
            "verdict",
            "gate_result",
            "output",
            "error",
            "posted_review_id",
            "verdict_posted_at",
            "approval_dismissed_at",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        # Only the fields NOT declared above: DataclassSerializer rejects a field that is both
        # explicitly declared and named here.
        read_only_fields = ["id", "head_sha", "error", "created_at", "updated_at"]
        extra_kwargs = {
            "head_sha": {"help_text": "Commit SHA of the PR head at the time this run started."},
            "error": {"help_text": "Error message if the run failed, blank otherwise."},
            "created_at": {"help_text": "When the review run was created."},
            "updated_at": {"help_text": "When the review run was last updated."},
        }


@extend_schema_serializer(component_name="DigestRun")
class DigestRunSerializer(DataclassSerializer):
    status = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in DigestRunStatus],
        read_only=True,
        help_text="Current state of the digest run (pending, completed, failed).",
    )
    resolution_source = serializers.ChoiceField(
        choices=[(s.value, s.name) for s in ChannelResolutionSource],
        read_only=True,
        help_text=(
            "Why the digest went to this channel: 'slack_name_match' (no declaration anywhere, so the "
            "audience_key matched a same-named Slack channel), 'stamphog_config' (the channel the repo "
            "declared under 'digest:' in .stamphog/policy.yml), 'owners_contact' (a teams: entry in a "
            "root owners.yaml named it), or 'manual' (no longer produced)."
        ),
    )
    posted_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the digest was posted to Slack, if it was.",
    )
    # The rendered summary is deliberately NOT exposed here: it's generated from each PR's body_excerpt,
    # so it reproduces repository content a project member without GitHub repo access must not read. It
    # lives only in the Slack post (whose audience already has channel access).

    class Meta:
        dataclass = contracts.DigestRunDTO
        fields = [
            "id",
            "audience_key",
            "slack_channel_id",
            "slack_channel_name",
            "resolution_source",
            "status",
            "pr_count",
            "slack_message_ts",
            "error",
            "created_at",
            "posted_at",
        ]
        # Only the fields NOT declared above (see ReviewRunSerializer).
        read_only_fields = [
            "id",
            "audience_key",
            "slack_channel_id",
            "slack_channel_name",
            "pr_count",
            "slack_message_ts",
            "error",
            "created_at",
        ]
        extra_kwargs = {
            "audience_key": {
                "help_text": "Digest bucket this run drained, e.g. a team slug or 'repo:PostHog/posthog'."
            },
            "slack_channel_id": {"help_text": "Slack channel this digest was posted to, e.g. 'C012AB3CD'."},
            "slack_channel_name": {"help_text": "Human-readable name of that channel, for display."},
            "pr_count": {"help_text": "Number of merged PRs included in the posted digest."},
            "slack_message_ts": {"help_text": "Slack message timestamp of the posted digest, if posted."},
            "error": {"help_text": "Error message if the run failed, blank otherwise."},
            "created_at": {"help_text": "When the digest run was created."},
        }


class StamphogRepoConfigWriteSerializer(serializers.Serializer):
    """Input shape for creating/updating a repo config.

    Separate from the read serializer because the contract is an output shape: it carries a
    required id, which a create request has no way to supply. Same split as visual_review's
    input serializers.

    installation_id is deliberately absent: it may only ever be set by the verified
    sync_installation flow, which proves the caller owns the installation before binding it. A
    client-supplied value on this path is ignored, so a manually created config carries no
    installation and simply won't resolve webhooks until synced.
    """

    provider = serializers.CharField(
        required=False, help_text="SCM provider this config talks to. Defaults to 'github'."
    )
    repository = serializers.CharField(help_text="Repository full name, e.g. 'PostHog/posthog'.")
    enabled = serializers.BooleanField(
        required=False, help_text="Whether stamphog actively reviews pull requests for this repo."
    )
    digest_enabled = serializers.BooleanField(
        required=False, help_text="Whether merged PRs on this repo are captured for the daily Slack digest."
    )
    review_mode = serializers.ChoiceField(
        choices=[(m.value, m.value) for m in ReviewMode],
        required=False,
        help_text=(
            "When reviews run: 'all' reviews every pull request (the default); 'label' reviews "
            "only pull requests carrying the trigger label, mirroring the Action's opt-in flow."
        ),
    )
    trigger_label = serializers.CharField(
        required=False,
        help_text=("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    )

    def __init__(
        self,
        *args,
        partial_update: bool = False,
        current: contracts.RepoConfigDTO | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # A PATCH sends only the changed fields, so the digest rule below needs the stored row to
        # judge a write that leaves `enabled` untouched.
        self.current = current
        if partial_update:
            # provider + repository are the config's identity: they resolve inbound webhooks and anchor
            # every PullRequest/ReviewRun FK. Editing them on an existing row would reroute that history
            # to a different repo and stop the original repo's webhooks from resolving, so on update
            # they are dropped rather than applied.
            self.fields.pop("provider")
            self.fields.pop("repository")

    def validate_trigger_label(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Trigger label cannot be blank.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # The digest reports what stamphog approved, so it has nothing to report without the review
        # path running.
        attrs = super().validate(attrs)
        enabled = attrs.get("enabled", self.current.enabled if self.current else True)
        if enabled:
            return attrs
        if attrs.get("digest_enabled"):
            raise serializers.ValidationError(
                {"digest_enabled": "Digests report what stamphog approved, so they need 'enabled' set to true."}
            )
        # Turning reviews off takes the digest with it rather than failing the write — the same
        # pairing the soft-delete tombstone applies, and the Enabled toggle sends only `enabled`.
        attrs["digest_enabled"] = False
        return attrs
