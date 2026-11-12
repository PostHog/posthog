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

from posthog.api.fields import RepeatedOrCommaSeparatedListField

from ..facade import contracts
from ..facade.enums import (
    ChannelResolutionSource,
    DigestRunStatus,
    LlmSkipReason,
    OwnerKind,
    OwnersFileStatus,
    PinReason,
    ReviewMode,
    ReviewRunStatus,
    ReviewTrigger,
    ReviewVerdict,
    RoutingMode,
    RoutingOwnerOutcome,
    RoutingOwnerReason,
    RoutingRunOrdering,
    RoutingScope,
    RoutingStatus,
)

# GitHub refuses a label name longer than this.
GITHUB_LABEL_MAX_LENGTH = 50
FORK_LABELS_MAX_ENTRIES = 100


class _GateResultSummarySerializer(serializers.Serializer):
    """Allowlisted, content-free slice of ``ReviewRun.gate_result``.

    The raw gate blob nests ``gates``, ``classification``, and ``policy`` sub-objects that carry
    repository content — changed-file paths (``lifted_files``, ``invalid_folder_files``),
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
    and default-branch policy file contents, none of which the API returns. The reviewer's reasoning,
    the text stamphog posts on GitHub, is parsed out of the stdout and returned as ``reasoning``.
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
    user_access_level = serializers.SerializerMethodField(
        read_only=True,
        help_text=(
            "The caller's access level on the stamphog resource, resolved for the team that owns this "
            "row. 'editor' can turn reviews on. 'manager' is required to turn them off or to change "
            "review_mode, trigger_label, routing_mode, routing_fork_labels or review_on_clean_external_review."
        ),
    )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_user_access_level(self, _obj: contracts.RepoConfigDTO) -> str | None:
        """The resource-wide level, not an object-level one: stamphog has no per-object rules.

        The frontend gates the review settings on this rather than on the app context, which is
        resolved for the environment in the URL while these rows belong to its parent project. The
        view resolves it once per request, so every row on a page reports the same level.
        """
        view = self.context.get("view")
        return view.stamphog_access_level if view else None

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
        choices=ReviewMode.choices,
        read_only=True,
        help_text=(
            "When reviews run: 'label' reviews only pull requests carrying the trigger label (the "
            "default), mirroring the Action's opt-in flow; 'all' reviews every pull request."
        ),
    )
    routing_mode = serializers.ChoiceField(
        choices=RoutingMode.choices,
        read_only=True,
        help_text=(
            "When stamphog requests reviews from the code owners in the repository's owners.yaml: 'off' (the "
            "default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' "
            "only when stamphog does not approve, where an approval requests only the owners of sensitive and "
            "new paths."
        ),
    )
    routing_fork_labels = serializers.DictField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an "
            "outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are "
            "GitHub label names. A team with no entry gets a review request as usual."
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
            "routing_mode",
            "routing_fork_labels",
            "review_on_clean_external_review",
            "user_access_level",
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
            "review_on_clean_external_review": {
                "read_only": True,
                "help_text": (
                    "Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a "
                    "silent stamphog review of that head, whatever review_mode says. A silent review posts only an "
                    "approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode "
                    "'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting "
                    "review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent "
                    "review before routing. Defaults to false."
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
            "GitHub install URL (github.com/apps/<slug>/installations/new) the 'Connect' button opens. The "
            "user picks a GitHub account there and chooses which repositories the App can reach, including "
            "an account where the App is already installed. Blank if the App slug is unconfigured."
        ),
    )
    authorize_url = serializers.CharField(
        read_only=True,
        help_text=(
            "GitHub authorize URL (github.com/login/oauth/authorize). GitHub's redirect after configuring an "
            "existing installation carries no OAuth code, so the client passes through this URL once: an "
            "installed App redirects straight back with a code, which sync_installation uses to prove "
            "ownership. Blank if the App client id is unconfigured."
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
    """Result of syncing an installation: the team's rows bound to it, and what the team can add now."""

    synced = StamphogRepoConfigSerializer(
        many=True,
        read_only=True,
        help_text=(
            "Repo configs this team already had for the installation's repositories, now bound to it. "
            "A sync creates no repo config: use add_repository to turn reviews on for a repository."
        ),
    )
    skipped = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Repository full names skipped because another team already owns them under this installation.",
    )
    available_count = serializers.IntegerField(
        read_only=True,
        help_text=(
            "How many repositories this team can add after the sync, across all its connected installations. "
            "List them with available_repositories."
        ),
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


class StamphogAvailableRepositoriesQuerySerializer(serializers.Serializer):
    """Query parameters for listing the repositories a team can add."""

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Case-insensitive substring to match against the repository full name, e.g. 'posthog'.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=50,
        min_value=1,
        max_value=200,
        help_text="Maximum number of repositories to return. Defaults to 50, at most 200.",
    )


class StamphogAvailableRepositoriesSerializer(serializers.Serializer):
    """Repositories from the team's connected GitHub installations that are not added to stamphog yet."""

    repositories = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Repository full names the team can add, sorted by name and capped by limit. Only repositories "
            "a project member proved access to on GitHub are listed, and never one another project already "
            "holds under the same installation."
        ),
    )
    total_count = serializers.IntegerField(
        read_only=True,
        help_text="How many repositories match the search in total, before limit applies.",
    )
    has_installation = serializers.BooleanField(
        read_only=True,
        help_text=(
            "Whether a project member connected a GitHub installation yet. False means GitHub must be "
            "connected before any repository can be added. True with a total_count of 0 and no search "
            "means no repository is left to add."
        ),
    )


class StamphogAddRepositorySerializer(serializers.Serializer):
    """Request body for turning reviews on for a repository from a connected installation."""

    repository = serializers.CharField(
        help_text=(
            "Repository full name, e.g. 'PostHog/posthog'. It must be in one of the project's connected "
            "GitHub installations, as available_repositories lists them. A repository the project already "
            "has is turned back on."
        ),
    )


@extend_schema_serializer(component_name="StamphogPullRequestRouting")
class PullRequestRoutingSerializer(DataclassSerializer):
    status = serializers.ChoiceField(
        choices=RoutingStatus.choices,
        read_only=True,
        help_text=(
            "The phase of the latest routing record: 'waiting' (fallback mode, the head waits for stamphog's "
            "verdict or the safety net), 'routing' (a task holds the claim and requested nobody yet), "
            "'requested' (the review requests went out, the routing comment is not finished) or 'done'."
        ),
    )
    mode = serializers.ChoiceField(
        choices=RoutingMode.choices,
        read_only=True,
        help_text="The repository's routing_mode when the record was written. Compare with the pull request's routing_mode.",
    )
    scope = serializers.ChoiceField(
        choices=RoutingScope.choices,
        read_only=True,
        allow_null=True,
        help_text=(
            "'full', or 'pinned' when a stamphog approval asks only the owners of sensitive and new paths. "
            "Null while the record waits."
        ),
    )

    class Meta:
        dataclass = contracts.PullRequestRoutingDTO
        # Only the fields NOT declared above (see ReviewRunSerializer).
        read_only_fields = [
            "head_sha",
            "trigger",
            "claim_expired",
            "waiting_since",
            "claimed_at",
            "routed_at",
            "full_routed_head",
            "pinned_routed_head",
        ]
        extra_kwargs = {
            "head_sha": {"help_text": "The head commit the record is for. It can be older than the pull request head."},
            "trigger": {
                "help_text": (
                    "What started the record: 'opened', 'ready_for_review', 'verdict:<outcome>', 'external_review', "
                    "'approval_retracted' or 'safety_net'."
                )
            },
            "claim_expired": {
                "help_text": (
                    "True when a 'routing' or 'requested' claim is older than the takeover limit. The task can "
                    "still be alive, and a later delivery does not always finish an expired 'requested' claim."
                )
            },
            "waiting_since": {
                "allow_null": True,
                "help_text": "When the head started to wait for stamphog's verdict. Null unless waiting.",
            },
            "claimed_at": {"allow_null": True, "help_text": "When a task claimed the pull request for this record."},
            "routed_at": {
                "allow_null": True,
                "help_text": "When the claim planned its requests. Null until the plan is saved.",
            },
            "full_routed_head": {
                "help_text": (
                    "The head that a full routing of this pull request requested owners for, blank if none. "
                    "Fallback mode routes in full at most once per pull request."
                )
            },
            "pinned_routed_head": {
                "help_text": "The latest approved head whose pinned owners were requested, blank if none."
            },
        }


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
    routing_mode = serializers.ChoiceField(
        choices=RoutingMode.choices,
        read_only=True,
        help_text="The repository's routing_mode now. 'off' means reviewer routing does not run for new events.",
    )
    routing = PullRequestRoutingSerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "The latest reviewer routing record of the pull request, or null when routing never wrote one: "
            "routing is off, the pull request is still a draft, or no routing event arrived yet. Use the "
            "routing runs list for the owners each run requested or cut."
        ),
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
            "routing_mode",
            "routing",
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


class _ReviewReasoningSerializer(serializers.Serializer):
    """The reviewer's reasoning for one run, the same text stamphog posts as its GitHub review."""

    reasoning = serializers.CharField(
        read_only=True, allow_null=True, help_text="The reviewer's explanation of its verdict."
    )
    showstoppers = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        allow_null=True,
        help_text="Issues the reviewer found that block approval.",
    )
    review_body = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="The review text stamphog posts on GitHub: the reasoning, the judgment points, and the gate outcome.",
    )
    change_summary = serializers.CharField(
        read_only=True, allow_null=True, help_text="A plain-language summary of what the change does."
    )


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
        choices=ReviewTrigger.choices,
        read_only=True,
        help_text=(
            "What caused this run to exist: self-driving inbox provenance, a manual request through the API, a clean "
            "PostHog Review run (a silent review that posts only an approval), the repo's trigger label, or the repo "
            "reviewing every PR event."
        ),
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
            "Allowlisted subset of the reviewer output blob (stamphog version, reviewer exit code). The raw "
            "reviewer stdout, PR payload, changed-file patches, and policy file contents are excluded. "
            "The reviewer's reasoning, the text stamphog posts on GitHub, is in `reasoning` instead."
        ),
    )

    reasoning = serializers.SerializerMethodField(
        help_text=(
            "The reviewer's reasoning, the same text stamphog posts as its GitHub review. Returned only when "
            "retrieving a single run, and null in list results. Its fields are null until the reviewer has run."
        ),
    )

    @extend_schema_field(_ReviewReasoningSerializer(allow_null=True))
    def get_reasoning(self, _obj: contracts.ReviewRunDTO) -> dict[str, object] | None:
        # The view puts the parsed reasoning in the context on retrieve only, so list pages stay small.
        reasoning = self.context.get("reasoning")
        return _ReviewReasoningSerializer(reasoning).data if reasoning is not None else None

    @extend_schema_field(_ReviewOutputSummarySerializer)
    def get_output(self, obj: contracts.ReviewRunDTO) -> dict[str, object]:
        # Explicit allowlist: never echo reviewer_raw / pr / files / policy_files out of the API.
        raw = obj.output or {}
        return {key: raw[key] for key in contracts.REVIEW_RUN_OUTPUT_SUMMARY_KEYS if key in raw}

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
            "reasoning",
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


class ReviewRequestSerializer(serializers.Serializer):
    """Request body for asking stamphog to review one pull request."""

    repository = serializers.CharField(
        help_text="Full name of the GitHub repository, e.g. 'PostHog/posthog'. It must be connected and enabled in Stamphog."
    )
    pr_number = serializers.IntegerField(min_value=1, help_text="Pull request number on GitHub.")


class ReviewRequestResponseSerializer(serializers.Serializer):
    """The review run a request points at."""

    run = ReviewRunSerializer(
        read_only=True,
        help_text=(
            "The review run for the pull request's current head. Poll it by id until status is terminal "
            "(completed, gated, failed, or superseded)."
        ),
    )
    created = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when this request queued a new run. False when a queued, running, or finished run already "
            "covered the current head, which is returned instead."
        ),
    )


# Every field carries a default because DigestRun.summary is a JSON blob whose shape grew over time.
# A run stored before a key existed, or one that never summarized anything ({}), still renders.
class _DigestSummaryPRSerializer(serializers.Serializer):
    """One merged pull request as the digest listed it."""

    pr_number = serializers.IntegerField(read_only=True, default=0, help_text="Pull request number on GitHub.")
    title = serializers.CharField(read_only=True, default="", help_text="Pull request title.")
    url = serializers.CharField(read_only=True, default="", help_text="Full URL to the pull request on GitHub.")
    author_login = serializers.CharField(
        read_only=True, default="", help_text="GitHub login of the pull request author."
    )
    summary = serializers.CharField(
        read_only=True, default="", help_text="The one-line summary of the change that the digest posted."
    )
    repository = serializers.CharField(
        read_only=True, default="", help_text="Repository full name, e.g. 'PostHog/posthog'. Blank on older runs."
    )


class _DigestSummarySerializer(serializers.Serializer):
    """What the digest posted to Slack: the headline and the pull requests it listed."""

    headline = serializers.CharField(
        read_only=True,
        default="",
        help_text="Prose about the merges with real consequence. Blank when the digest led with its first line.",
    )
    prs = _DigestSummaryPRSerializer(
        many=True,
        read_only=True,
        default=list,
        help_text="The merged pull requests the digest listed, in the order it listed them.",
    )


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
    summary = serializers.SerializerMethodField(
        help_text=(
            "What the digest posted: its headline and the merged pull requests it listed. "
            "Both are empty on a run with nothing to post, and on runs stored before this format."
        ),
    )

    @extend_schema_field(_DigestSummarySerializer)
    def get_summary(self, obj: contracts.DigestRunDTO) -> dict[str, object]:
        # The digest writes each line from the PR title and the reviewer's change_summary, and both
        # already reach any project member through the pull request and review run APIs. Summaries
        # stored before the prompt dropped body_excerpt were written from PR bodies, which a member
        # without GitHub repo access must not read. The same change added the `judged` key, so a
        # summary without it is withheld. Keep body_excerpt out of the digest prompt, or this leaks it.
        stored = obj.summary if "judged" in obj.summary else {}
        return _DigestSummarySerializer(stored).data

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
            "summary",
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
        required=False,
        help_text="SCM provider this config talks to. Defaults to 'github'. Set on create only, an update ignores it.",
    )
    repository = serializers.CharField(
        help_text="Repository full name, e.g. 'PostHog/posthog'. Set on create only, an update ignores it."
    )
    enabled = serializers.BooleanField(
        required=False, help_text="Whether stamphog actively reviews pull requests for this repo."
    )
    digest_enabled = serializers.BooleanField(
        required=False, help_text="Whether merged PRs on this repo are captured for the daily Slack digest."
    )
    review_mode = serializers.ChoiceField(
        choices=ReviewMode.choices,
        required=False,
        help_text=(
            "When reviews run: 'label' reviews only pull requests carrying the trigger label (the "
            "default), mirroring the Action's opt-in flow; 'all' reviews every pull request."
        ),
    )
    trigger_label = serializers.CharField(
        required=False,
        help_text=("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    )
    routing_mode = serializers.ChoiceField(
        choices=RoutingMode.choices,
        required=False,
        help_text=(
            "When stamphog requests reviews from the code owners in the repository's owners.yaml: 'off' (the "
            "default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' "
            "only when stamphog does not approve, where an approval requests only the owners of sensitive and "
            "new paths."
        ),
    )
    routing_fork_labels = serializers.DictField(
        child=serializers.CharField(max_length=GITHUB_LABEL_MAX_LENGTH),
        required=False,
        help_text=(
            "On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an "
            "outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are "
            "GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces "
            "the whole map, and an empty object removes every label."
        ),
    )
    review_on_clean_external_review = serializers.BooleanField(
        required=False,
        help_text=(
            "Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a "
            "silent stamphog review of that head, whatever review_mode says. A silent review posts only an "
            "approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode "
            "'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting "
            "review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent "
            "review before routing. Defaults to false."
        ),
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

    def validate_routing_fork_labels(self, value: dict[str, str]) -> dict[str, str]:
        if len(value) > FORK_LABELS_MAX_ENTRIES:
            raise serializers.ValidationError(f"Map at most {FORK_LABELS_MAX_ENTRIES} teams to a label.")
        labels: dict[str, str] = {}
        for slug, label in value.items():
            slug, label = slug.strip(), label.strip()
            if not slug or slug.startswith("@"):
                raise serializers.ValidationError("Each key must be an owners.yaml team slug, not a person.")
            if not label:
                raise serializers.ValidationError(f"The label for {slug} cannot be blank.")
            labels[slug] = label
        return labels

    def validate_trigger_label(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Trigger label cannot be blank.")
        return value

    def _validate_clean_review_switch(self, attrs: dict[str, Any]) -> None:
        # In 'all' mode every pull request gets a visible review already, so the switch would only
        # make fallback routing wait for a silent review that never comes.
        review_mode = attrs.get("review_mode", self.current.review_mode if self.current else ReviewMode.LABEL)
        if review_mode != ReviewMode.ALL:
            return
        if attrs.get("review_on_clean_external_review"):
            raise serializers.ValidationError(
                {
                    "review_on_clean_external_review": (
                        "This setting works only when review_mode is 'label', because 'all' reviews every pull "
                        "request already."
                    )
                }
            )
        if "review_mode" in attrs:
            attrs["review_on_clean_external_review"] = False

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        self._validate_clean_review_switch(attrs)
        # The digest reports what stamphog approved, so it has nothing to report without the review
        # path running.
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


class StamphogOwnersFileSerializer(serializers.Serializer):
    """Whether a repository can use reviewer requests, which read ownership from its owners.yaml."""

    owners_file = serializers.ChoiceField(
        choices=OwnersFileStatus.choices,
        help_text=(
            "Whether the default branch has a root owners.yaml: 'found', 'missing', or 'unavailable' when "
            "the check could not ask GitHub (no installation, or GitHub answered with an error)."
        ),
    )


class StamphogRoutingRunsQuerySerializer(serializers.Serializer):
    """Query parameters for listing reviewer routing runs."""

    repository = serializers.CharField(
        required=False, help_text="Filter by repository full name, e.g. 'PostHog/posthog'."
    )
    pr_number = serializers.IntegerField(required=False, help_text="Filter by pull request number.")
    owner = serializers.CharField(
        required=False,
        help_text=(
            "Keep only runs that decided about this owner, spelled as in owners.yaml: a team slug such as "
            "'team-devex', or a GitHub login such as '@octocat'."
        ),
    )
    outcome = RepeatedOrCommaSeparatedListField(
        child=serializers.ChoiceField(choices=RoutingOwnerOutcome.choices),
        required=False,
        help_text=(
            "Keep only runs where an owner got one of these outcomes. Pass several as a comma-separated list or repeat the parameter. "
            "With `owner`, that owner must have one of them, so `owner=team-devex&outcome=cut` lists the runs "
            "that cut team-devex."
        ),
    )
    reason = serializers.ChoiceField(
        choices=RoutingOwnerReason.choices,
        required=False,
        help_text="Keep only runs where an owner was kept or cut for this reason. With `owner`, that owner must have it.",
    )
    head_sha = serializers.CharField(
        required=False,
        max_length=64,
        help_text="Keep only runs on this head commit. Pass the full 40-character SHA.",
    )
    created_after = serializers.DateTimeField(
        required=False, help_text="Keep only runs created at or after this time (ISO 8601)."
    )
    created_before = serializers.DateTimeField(
        required=False, help_text="Keep only runs created before this time (ISO 8601)."
    )
    latest_per_pr = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Keep only the newest run of each pull request. The newest run is picked over the pull request's whole "
            "history first, and every other filter then applies to it: a pull request whose newest run fails a "
            "filter drops out and is never replaced by an older run. With this flag, `count` counts pull requests."
        ),
    )
    merged = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text=(
            "true keeps runs of merged pull requests. false keeps runs of pull requests that are not merged: open "
            "ones and ones closed without merging, because stamphog does not record a close. Omit for both."
        ),
    )
    merged_after = serializers.DateTimeField(
        required=False,
        help_text="Keep only runs of pull requests merged at or after this time (ISO 8601). Only merged pull requests match.",
    )
    merged_before = serializers.DateTimeField(
        required=False,
        help_text="Keep only runs of pull requests merged before this time (ISO 8601). Only merged pull requests match.",
    )
    ordering = serializers.ChoiceField(
        choices=RoutingRunOrdering.choices,
        required=False,
        help_text=(
            "'-created_at' (the default) lists the newest run first. '-merged_at' lists the newest merge first, "
            "then the newest run, with unmerged pull requests last."
        ),
    )


SIZE_NULL_HELP = "{}. Null until the pull request merges, because stamphog stores the size at merge."


@extend_schema_serializer(component_name="StamphogRoutingPullRequest")
class RoutingPullRequestSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.RoutingPullRequestDTO
        extra_kwargs = {
            "title": {"help_text": "The pull request title, as stamphog last saw it."},
            "author": {"help_text": "The GitHub login of the pull request author."},
            "url": {"help_text": "Link to the pull request on GitHub."},
            "merged_at": {"help_text": "When the pull request merged. Null when it is not merged."},
            "additions": {"allow_null": True, "help_text": SIZE_NULL_HELP.format("Added lines")},
            "deletions": {"allow_null": True, "help_text": SIZE_NULL_HELP.format("Deleted lines")},
            "changed_files": {"allow_null": True, "help_text": SIZE_NULL_HELP.format("Changed files")},
            "summary": {
                "allow_null": True,
                "help_text": (
                    "The stamphog reviewer's one sentence about the whole change, from the newest completed review "
                    "of the pull request that wrote one, at any head. Null when no review wrote one."
                ),
            },
            "approved_by_stamphog": {
                "help_text": (
                    "Whether a standing stamphog approval (posted at the head, or kept there because the diff did "
                    "not change) covers the head this routing run decided on. That is the head routing last "
                    "decided on with latest_per_pr, which is usually but not always the merged head."
                )
            },
        }


@extend_schema_serializer(component_name="StamphogRoutingPin")
class RoutingPinSerializer(DataclassSerializer):
    reason = serializers.ChoiceField(
        choices=PinReason.choices, read_only=True, help_text="Why the path pins its owner."
    )

    class Meta:
        dataclass = contracts.RoutingPinDTO
        extra_kwargs = {
            "path": {"help_text": "The changed path, or the new directory, that pinned the owner."},
        }


@extend_schema_serializer(component_name="StamphogRoutingFile")
class RoutingFileSerializer(DataclassSerializer):
    class Meta:
        dataclass = contracts.RoutingFileDTO
        extra_kwargs = {
            "path": {"help_text": "The changed path."},
            "previous_path": {"help_text": "The path before a rename. Null for any other change."},
            "status": {"help_text": "GitHub's file status, such as 'added', 'modified', 'removed' or 'renamed'."},
            "additions": {"help_text": "Added lines."},
            "deletions": {"help_text": "Deleted lines."},
            "owners_source": {
                "help_text": (
                    "Repo-relative path of the ownership file, read at the run's owners_sha, whose `owners` list names "
                    "this owner for the file. Null when only an additions declaration made the owner a candidate (see "
                    "the owner's `new_path` pins), or when the run is older than this field."
                )
            },
        }


@extend_schema_serializer(component_name="StamphogRoutingRunOwner")
class RoutingRunOwnerSerializer(DataclassSerializer):
    outcome = serializers.ChoiceField(
        choices=RoutingOwnerOutcome.choices,
        read_only=True,
        help_text=(
            "What the run did with the owner: 'requested', 'labeled' (a fork label instead of a request), "
            "'refused' (GitHub refused the request or the label), 'cut', 'not_requested' (stamphog approved, and routing "
            "would have asked this owner without the approval; on an older run whose llm_skipped is 'stamphog_approved' "
            "it means only that the owner owns changed code) or 'already_requested' (an earlier run asked this pinned "
            "owner)."
        ),
    )
    reason = serializers.ChoiceField(
        choices=RoutingOwnerReason.choices,
        read_only=True,
        help_text=(
            "Why: 'sensitive' or 'new_path' (pinned, never cut), 'largest_owner' (a pull request keeps "
            "at least one reviewer), 'diff_not_seen' (the model did not see all of the owner's diff), "
            "'cut_skipped' (no model call, see llm_skipped on the run), 'model_kept', 'model_cut' or "
            "'stamphog_approved' (older runs only)."
        ),
    )
    pins = RoutingPinSerializer(
        many=True, read_only=True, help_text="The changed paths that pinned the owner, so no cut could remove them."
    )
    kind = serializers.ChoiceField(
        choices=OwnerKind.choices, read_only=True, help_text="Whether the owner is a GitHub team or a person."
    )

    top_files = RoutingFileSerializer(
        many=True,
        read_only=True,
        help_text="Up to 3 of the files this owner owns, the most changed lines first. Get one run for all of them.",
    )

    class Meta:
        dataclass = contracts.RoutingRunOwnerDTO
        exclude = ["files"]
        extra_kwargs = {
            "owner": {
                "help_text": (
                    "The owner as owners.yaml spells it: a team slug such as 'team-devex', or a GitHub login "
                    "such as '@octocat'."
                )
            },
            "model_reason": {
                "help_text": (
                    "The model's one-line reason to cut this owner. Also set when a guard kept the owner anyway. "
                    "Blank when the model proposed no cut for them."
                )
            },
            "lines": {"help_text": "Changed lines in the files this owner owns."},
            "file_count": {"help_text": "Changed files this owner owns."},
            "summary": {
                "allow_null": True,
                "help_text": (
                    "The stamphog reviewer's clause about this owner's part of the change. Set only when the "
                    "reviewer wrote one clause per owning team, which it does when several teams own changed files."
                ),
            },
        }


@extend_schema_serializer(component_name="StamphogRoutingRunOwnerDetail")
class RoutingRunOwnerDetailSerializer(RoutingRunOwnerSerializer):
    files = RoutingFileSerializer(
        many=True,
        read_only=True,
        help_text="Every changed file this owner owns, which is what made them a candidate. Patches are not kept.",
    )

    class Meta:
        dataclass = contracts.RoutingRunOwnerDTO
        extra_kwargs = RoutingRunOwnerSerializer.Meta.extra_kwargs


@extend_schema_serializer(component_name="StamphogRoutingRun")
class RoutingRunSerializer(DataclassSerializer):
    mode = serializers.ChoiceField(
        choices=RoutingMode.choices,
        read_only=True,
        help_text="The repository's routing_mode when the run made its requests.",
    )
    owners = RoutingRunOwnerSerializer(
        many=True, read_only=True, help_text="The run's decision for every owner of the changed code."
    )
    scope = serializers.ChoiceField(
        choices=RoutingScope.choices,
        read_only=True,
        help_text="'full', or 'pinned' when a stamphog approval asked only the owners of sensitive and new paths.",
    )
    llm_skipped = serializers.ChoiceField(
        choices=LlmSkipReason.choices,
        read_only=True,
        allow_null=True,
        help_text="Why the cut step made no model call. Null when it made one.",
    )
    pull_request = RoutingPullRequestSerializer(
        read_only=True,
        help_text="The pull request the run routed, as stamphog last saw it rather than as it was at the run.",
    )

    class Meta:
        dataclass = contracts.RoutingRunDTO
        fields = [
            "id",
            "repository",
            "pr_number",
            "pull_request",
            "head_sha",
            "mode",
            "trigger",
            "scope",
            "fork",
            "llm_skipped",
            "model",
            "files_truncated",
            "additions_resolved",
            "owners_sha",
            "owners",
            "created_at",
        ]
        extra_kwargs = {
            "id": {"help_text": "ID of the routing run."},
            "repository": {"help_text": "Full name of the repository."},
            "pr_number": {"help_text": "Pull request number."},
            "head_sha": {"help_text": "The head commit the run routed."},
            "trigger": {
                "help_text": (
                    "What started the run: 'opened', 'ready_for_review', 'verdict:<outcome>', 'external_review', "
                    "'approval_retracted' or 'safety_net'."
                )
            },
            "fork": {"help_text": "Whether the pull request came from a fork, which skips the model."},
            "model": {"help_text": "The model the cut request reached. Blank when no request reached the gateway."},
            "files_truncated": {
                "help_text": "Whether GitHub listed fewer files than the pull request changes, so owners may be missing."
            },
            "additions_resolved": {
                "help_text": "Whether the new-path lookup worked. When false, owners of new paths may not be pinned."
            },
            "owners_sha": {
                "help_text": "The default-branch commit whose owners.yaml files decided the owners. Blank when unknown."
            },
            "created_at": {"help_text": "When the run made its requests."},
        }


class StamphogRoutingOwnersQuerySerializer(serializers.Serializer):
    """Query parameters for listing the owners routing runs decided about."""

    created_after = serializers.DateTimeField(
        required=False,
        help_text="Count only runs created at or after this time (ISO 8601). Defaults to 90 days ago.",
    )


@extend_schema_serializer(component_name="StamphogRoutingOwnerCount")
class RoutingOwnerCountSerializer(DataclassSerializer):
    kind = serializers.ChoiceField(
        choices=OwnerKind.choices, read_only=True, help_text="Whether the owner is a GitHub team or a person."
    )

    class Meta:
        dataclass = contracts.RoutingOwnerCountDTO
        extra_kwargs = {
            "owner": {
                "help_text": "The owner as owners.yaml spells it: a team slug such as 'team-devex', or a login such as '@octocat'."
            },
            "pr_count": {
                "help_text": "Distinct pull requests whose routing runs decided about this owner in the window."
            },
        }


@extend_schema_serializer(component_name="StamphogRoutingRunDetail")
class RoutingRunDetailSerializer(RoutingRunSerializer):
    owners = RoutingRunOwnerDetailSerializer(
        many=True,
        read_only=True,
        help_text="The run's decision for every owner of the changed code, with the files each owner owns.",
    )
