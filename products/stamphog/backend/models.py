"""
Django models for stamphog.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import (
    AudienceReason,
    ChannelResolutionSource,
    DigestRunStatus,
    LlmSkipReason,
    OwnerKind,
    ReviewMode,
    ReviewRunStatus,
    ReviewVerdict,
    RoutingMode,
    RoutingOwnerOutcome,
    RoutingOwnerReason,
    RoutingScope,
)
from .logic.review_trigger import is_silent_output


# Lives on a separate product database (see products/db_routing.yaml), so it
# inherits ProductTeamModel: team_id is a plain BigIntegerField (no cross-DB FK
# to Team) and the manager is fail-closed. See posthog/models/scoping/README.md.
class StamphogRepoConfig(ModelActivityMixin, ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # SCM provider this config talks to. GitHub is the only implemented provider
    # today, but the installation/repository identity is provider-scoped so the
    # field is part of the cross-team uniqueness identity.
    provider = models.CharField(max_length=32, default="github")
    # Full name in "owner/repo" form, matching the GitHub webhook payload.
    repository = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    installation_id = models.CharField(max_length=64)
    # Opt-in: capture merged PRs and fold them into the daily Slack digest. Independent of
    # `enabled` (review) so a repo can be reviewed without digests, or vice versa.
    digest_enabled = models.BooleanField(default=False)
    # LABEL (the default) reviews only PRs carrying trigger_label, mirroring the Action's label-gated
    # opt-in flow; ALL reviews every relevant PR event.
    review_mode = models.CharField(
        max_length=16,
        choices=ReviewMode.choices,
        default=ReviewMode.LABEL.value,
    )
    trigger_label = models.CharField(max_length=100, default="stamphog")
    # The PostHog user who connected this repo's installation (plain id, no FK — multi-DB product).
    # The review sandbox's short-lived LLM gateway token is minted under this identity, mirroring how
    # tasks mints under task.created_by. Null means "never synced": hosted reviews fail closed.
    connected_by_user_id = models.BigIntegerField(null=True, blank=True)
    # When to request reviews from the owners of the changed code (logic/routing/service.py).
    # db_default on both: the previous release still inserts rows without these columns during a deploy.
    routing_mode = models.CharField(
        max_length=16,
        choices=RoutingMode.choices,
        default=RoutingMode.OFF.value,
        db_default=RoutingMode.OFF.value,
    )
    # Team slug -> label name. A fork PR adds the label instead of requesting that team, so an
    # outside author cannot ping it.
    routing_fork_labels = models.JSONField(default=dict, db_default={})
    # Off by default: a clean external review starts a review outside review_mode, which widens when stamphog runs.
    review_on_clean_external_review = models.BooleanField(default=False, db_default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Inherit the base Meta so default_manager_name="all_teams" survives. A fresh `class Meta`
    # would drop it (Django doesn't merge parent Meta into a child's own), and correctness would
    # then rest on Django's MRO fallback — which only holds while this model declares no local
    # manager. Making it explicit keeps the fail-closed contract from silently regressing.
    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["team_id", "repository"], name="unique_stamphog_repo_per_team"),
            # Cross-team: one (provider, installation, repository) triple belongs to a single team. The
            # dedicated GitHub App can only be installed on a given repo once, so its installation_id
            # identifies exactly one repo under one team — two teams can't legitimately share it. This
            # backs the perform_create guard at the DB level (closes the check-then-act race) and its
            # unique index doubles as the webhook-resolution index for (provider, installation_id, repository).
            # Restricted to non-empty installation_id: a manually-created config before it's synced carries
            # a blank installation and proves no ownership, so blank rows must not globally reserve a repo —
            # otherwise one team's placeholder blocks every other team from creating the same one.
            models.UniqueConstraint(
                fields=["provider", "installation_id", "repository"],
                name="unique_stamphog_installation_repo",
                condition=~Q(installation_id=""),
            ),
        ]

    def __str__(self) -> str:
        return self.repository


class StamphogInstallation(ProductTeamModel):
    """One GitHub App installation a team connected, and the repositories a member proved access to.

    `repositories` is a snapshot of what the connecting members could reach with their own GitHub
    token, merged across syncs. It is not the installation's full repository list: an outside
    collaborator on one repository can reach the installation, and the installation token would
    show them every private repository in it. Only a repository in this snapshot can be added to
    the team without a manual placeholder. A removal webhook shrinks it between syncs, and no webhook
    grows it, because a webhook carries no user who proved access.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    provider = models.CharField(max_length=32, default="github")
    installation_id = models.CharField(max_length=64)
    # Full names in "owner/repo" form, matching StamphogRepoConfig.repository.
    repositories = models.JSONField(default=list)
    # The member who last proved access to this installation (plain id, no FK: multi-DB product).
    # A repository added from the snapshot takes this as its connecting user.
    connected_by_user_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Inherit the base Meta so default_manager_name="all_teams" survives (see StamphogRepoConfig.Meta).
    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "provider", "installation_id"], name="unique_stamphog_installation_per_team"
            ),
        ]
        indexes = [
            # Webhook team resolution reads every team that holds one installation.
            models.Index(fields=["provider", "installation_id"], name="stamphog_installation_lookup"),
        ]

    def __str__(self) -> str:
        return f"{self.provider} installation {self.installation_id}"


class PullRequest(ProductTeamModel):
    """One pull request stamphog knows about — the PR-grain context every review run shares.

    Refreshed on every relevant webhook delivery; merge state is filled in when the PR
    merges. A row is linked to a `DigestRun` once its merge has been summarized and posted.
    Unlinked, digest-eligible rows (audience_key set, digest_run NULL) are what the next
    digest picks up, so a failed post leaves them for tomorrow to retry.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    repo_config = models.ForeignKey(StamphogRepoConfig, on_delete=models.CASCADE, related_name="pull_requests")
    pr_number = models.IntegerField()
    title = models.CharField(max_length=512, blank=True)
    author_login = models.CharField(max_length=255, blank=True)
    pr_url = models.CharField(max_length=512, blank=True)
    # Branch name of the PR head (pull_request.head.ref). Named to match the
    # engineering_analytics / GitHub-DWH head_sha/head_branch/pr_number convention.
    head_branch = models.CharField(max_length=255, blank=True)
    # Trimmed PR description, capped at capture time to keep rows (and the LLM prompt) bounded.
    body_excerpt = models.TextField(blank=True)
    # Merge state — set when the PR merges, regardless of whether stamphog approved it.
    merged_at = models.DateTimeField(null=True)
    merge_commit_sha = models.CharField(max_length=64, blank=True)
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)
    changed_files = models.IntegerField(default=0)
    # Digest bucket resolved by the audience cascade (see logic/audiences.py) — stamped only
    # when the merged PR is digest-eligible (stamphog approved a run); the digest filters on it.
    audience_key = models.CharField(max_length=255, blank=True)
    # What the change does, copied from the run that approved the merged head. One sentence, plus
    # one clause per owning team when more than one team owns files in the merge. Written in the
    # sandbox with the diff in hand, which the daily digest no longer has. Blank when the engine
    # predates the field; the digest falls back to the PR title.
    summary_line = models.TextField(blank=True, default="")
    digest_run = models.ForeignKey("DigestRun", on_delete=models.SET_NULL, null=True, related_name="pull_requests")
    # Historical: the sticky comment a verdict used to be written into. Verdicts are reviews now, so
    # nothing writes this any more — it holds the last comment id from before that change. Kept
    # because it is on the facade contract; drop both together.
    posted_comment_id = models.BigIntegerField(null=True)
    # The PR's own pull_request.updated_at from the last payload we applied. GitHub can redeliver or
    # fan out an older snapshot after a newer one; this field is the monotonic clock that lets the task
    # drop a strictly-older delivery instead of superseding the current run with a stale review.
    payload_updated_at = models.DateTimeField(null=True)
    # The latest reviewer routing result for this PR (logic/routing/service.py). Null until routing
    # runs. Holds owner names and counts only, never PR content.
    routing = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Inherit the base Meta so default_manager_name="all_teams" survives (see StamphogRepoConfig.Meta).
    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "repo_config", "pr_number"], name="unique_stamphog_pull_request"
            ),
        ]
        indexes = [
            # Serves both digest hot paths, restricted to the small, draining set of digest-eligible
            # rows (digest_run NULL). Per-team digest: (team_id, audience_key) equality prefix + merged_at
            # range and sort. Cross-team discovery: the partial predicate confines the scan to unlinked
            # rows and the leading columns cover the distinct (team_id, audience_key) it selects.
            models.Index(
                fields=["team_id", "audience_key", "merged_at"],
                condition=Q(digest_run__isnull=True),
                name="stamphog_pr_pending_digest",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.repo_config.repository}#{self.pr_number}"


class PullRequestAudience(ProductTeamModel):
    """One digest audience a merged PR belongs to.

    A PR reaches a team because that team owns files the PR changed (`owned`), or because its repo
    declared one channel for everything it merges (`repo_declared`). One merge can land in several
    digests, since several teams can own parts of it. The claim marker
    lives here rather than on the PullRequest: with several audiences per PR, a single `digest_run`
    on the PR would let the first channel to claim it hide the merge from every other channel, and
    one channel's failed post would strand the PR for all of them.

    Membership is deliberately generous — any owning team gets a row. Whether the PR is actually
    worth mentioning to that team is decided later, when the digest is summarized.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name="audiences")
    audience_key = models.CharField(max_length=255)
    reason = models.CharField(max_length=32, choices=[(r.value, r.value) for r in AudienceReason])
    # A sample of this team's changed paths, from the review's ownership resolution. The digest uses
    # it to tell "this changed in your area" from a sweep that grazed two of your files, which it
    # cannot judge from the PR alone. Empty for an authored audience or an engine without the field.
    owned_files = models.JSONField(default=list)
    # How many of the PR's changed files this team owns, counting only what a person edited. Not
    # len(owned_files) — that list is a capped sample, and a team owning most of a large change must
    # not read as grazed by it. A file a build step wrote is not a stake, so it is not counted here.
    owned_file_count = models.IntegerField(default=0)
    digest_run = models.ForeignKey("DigestRun", on_delete=models.SET_NULL, null=True, related_name="audiences")
    created_at = models.DateTimeField(auto_now_add=True)

    # Inherit the base Meta so default_manager_name="all_teams" survives (see StamphogRepoConfig.Meta).
    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "pull_request", "audience_key"], name="unique_stamphog_pr_audience"
            ),
        ]
        indexes = [
            # The daily claim: unposted audiences for one channel's key.
            models.Index(fields=["team_id", "audience_key", "digest_run"], name="stamphog_audience_claim"),
        ]

    def __str__(self) -> str:
        return f"{self.audience_key} ({self.reason})"


class ReviewRun(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name="review_runs")
    head_sha = models.CharField(max_length=64)
    # GitHub webhook delivery id — unique so a redelivered event dedupes.
    delivery_id = models.CharField(max_length=64, null=True, unique=True)
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in ReviewRunStatus],
        default=ReviewRunStatus.QUEUED.value,
    )
    verdict = models.CharField(
        max_length=32,
        choices=[(v.value, v.value) for v in ReviewVerdict],
        default=ReviewVerdict.NONE.value,
    )
    gate_result = models.JSONField(null=True)
    output = models.JSONField(default=dict)
    # What the change does, from the reviewer's structured verdict: one sentence, plus one clause
    # per owning team when more than one team owns files in the merge. Its own field rather than a
    # slice of `output`, which mixes reviewer stdout with PR patches and policy contents. Copied
    # onto the PullRequest when the approved head is the one that merges. The width lives in the
    # reviewer schema (logic/reviewer.CHANGE_SUMMARY_MAX_CHARS), not in the column.
    change_summary = models.TextField(blank=True, default="")
    error = models.TextField(blank=True)
    # What we posted back to the SCM once the verdict was decided — recorded so a
    # re-review can find and update its own artifacts, and for audit. Populated by
    # the post_verdict activity (and the gate-block path) from the API responses.
    # Whether the verdict reached the PR, which a silent non-approval never does (`verdict_withheld`).
    verdict_posted_at = models.DateTimeField(null=True)
    posted_review_id = models.BigIntegerField(null=True)
    # Set when this run's GitHub APPROVE review was dismissed because the head moved. GitHub never
    # auto-dismisses an approval on a new push, so a later run stamps this after retracting the stale
    # one (see the dismiss_stale_approvals activity) — the flag also keeps a retry from re-dismissing.
    approval_dismissed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

    @property
    def is_silent(self) -> bool:
        """Whether the run posts only an approval, from the provenance stamped when it was queued."""
        return is_silent_output(self.output)

    def may_publish(self, verdict: str | None = None) -> bool:
        """Whether this run may write ``verdict`` to the PR. Without a verdict: whether it may write
        anything other than an approval, such as the 👀 cue, a refusal or a failure notice.

        Every path that writes to the PR asks this, so a silent run's single exception, the
        approval, is decided in one place.
        """
        return not self.is_silent or verdict == ReviewVerdict.APPROVED

    @property
    def verdict_withheld(self) -> bool:
        """A silent run that decided a verdict and kept it off the PR."""
        return (
            self.is_silent
            and self.status in (ReviewRunStatus.COMPLETED, ReviewRunStatus.GATED)
            and self.verdict_posted_at is None
        )

    def __str__(self) -> str:
        return f"{self.pull_request.repo_config.repository}#{self.pull_request.pr_number} ({self.status})"


class DigestRun(ProductTeamModel):
    """One posted (or attempted) daily digest: one audience, one destination, one day.

    The destination is recorded here rather than looked up through a channel row, because it is a
    historical fact. Routing is derived fresh from the repositories every run (see
    logic/channel_resolution.py), so a row pointing at mutable config would let a later
    re-declaration rewrite where a past digest claims it was posted.

    One audience can produce several runs on one day. A repository that declares a team's channel
    answers for its own merges, so a team's merges partition between destinations rather than
    picking a winner.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # The bucket this run drained, e.g. a team slug or "repo:owner/name".
    #
    # db_default on all four. During a rolling deploy the previous release still inserts rows here
    # without these columns, and Django applies default= in Python only. Without a database default,
    # those inserts fail the NOT NULL check for as long as both releases run.
    audience_key = models.CharField(max_length=255, default="", db_default="")
    slack_channel_id = models.CharField(max_length=64, default="", db_default="")
    slack_channel_name = models.CharField(max_length=255, blank=True, default="", db_default="")
    # How the destination was decided: the repo's own digest config, an owners.yaml entry, or a
    # plain name match on the slug. It is what answers "why did my digest go there".
    resolution_source = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in ChannelResolutionSource],
        default=ChannelResolutionSource.SLACK_NAME_MATCH.value,
        db_default=ChannelResolutionSource.SLACK_NAME_MATCH.value,
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in DigestRunStatus],
        default=DigestRunStatus.PENDING.value,
    )
    pr_count = models.IntegerField(default=0)
    # LLM (or fallback) summary output that was rendered into the Slack message.
    summary = models.JSONField(default=dict)
    slack_message_ts = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True)

    class Meta(ProductTeamModel.Meta):
        indexes = [
            # Two reads key off (team, audience). The first asks whether this audience ever posted,
            # which decides how far back its claim reaches. The second is the API's history listing.
            # Without this index both scan a table that grows by one row per audience per weekday.
            models.Index(fields=["team_id", "audience_key"], name="stamphog_digest_run_audience"),
        ]

    def __str__(self) -> str:
        return f"digest {self.audience_key} -> {self.slack_channel_name or self.slack_channel_id} ({self.status})"


class RoutingRun(ProductTeamModel):
    """One reviewer routing run that made its GitHub writes, kept as an append-only record.

    `PullRequest.routing` is the routing state and holds only the latest result. These rows keep
    every decision, so a reader can later tell why an owner was or was not asked to review. They
    hold owner names, counts, pinning paths and the model's one-line reasons, never the diff.
    """

    # Minted when the run plans, before the model call, so the LLM trace carries it too. A second write
    # of the same run fails on it rather than logging the run twice.
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name="routing_runs")
    head_sha = models.CharField(max_length=64)
    mode = models.CharField(max_length=16, choices=RoutingMode.choices)
    # `opened`, `ready_for_review`, `verdict:<outcome>` or `safety_net`.
    trigger = models.CharField(max_length=64)
    scope = models.CharField(max_length=16, choices=RoutingScope.choices)
    fork = models.BooleanField(default=False)
    # Why the cut step made no model call. Blank when it made one.
    llm_skipped = models.CharField(max_length=32, choices=LlmSkipReason.choices, blank=True)
    # The model that a request reached. Blank when no request reached the gateway.
    model = models.CharField(max_length=128, blank=True)
    # A partial file list or ownership read explains an owner that should have been pinned and was not.
    files_truncated = models.BooleanField(default=False)
    additions_resolved = models.BooleanField(default=True)
    # The default-branch commit whose owners.yaml files decided the candidates. With each owner's files,
    # it lets a reader resolve the run's owners again after owners.yaml changes.
    owners_sha = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(ProductTeamModel.Meta):
        indexes = [
            models.Index(fields=["team_id", "-created_at"], name="stamphog_routing_run_recent"),
        ]

    def __str__(self) -> str:
        return f"routing {self.trigger} at {self.head_sha[:10]}"


class RoutingRunOwner(ProductTeamModel):
    """What one routing run did with one owner of the changed code, and why."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # The unique constraint below leads with the run, so it serves the lookups a plain FK index would.
    run = models.ForeignKey(RoutingRun, on_delete=models.CASCADE, related_name="owners", db_index=False)
    # As owners.yaml spells it: `team-devex` or `@alice`.
    owner = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=OwnerKind.choices)
    outcome = models.CharField(max_length=32, choices=RoutingOwnerOutcome.choices)
    reason = models.CharField(max_length=32, choices=RoutingOwnerReason.choices)
    # The model's reason to cut this owner, cleaned as for the routing comment and scrubbed of credentials.
    # Also set when a guard kept the owner anyway, which is what an evaluation of the cut step needs.
    model_reason = models.TextField(blank=True)
    # The sensitive and new paths that pinned the owner, as `[{"reason": ..., "path": ...}]`.
    pins = models.JSONField(default=list)
    # Every changed file this owner owns, as GitHub listed it, without the patch. owners.yaml and the
    # pull request both move after the run, so the run keeps its own copy.
    files = models.JSONField(default=list)
    lines = models.PositiveIntegerField(default=0)
    file_count = models.PositiveIntegerField(default=0)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["run", "owner"], name="unique_stamphog_routing_run_owner"),
        ]
        indexes = [
            # Serves the owner filter of the run list, which asks why one owner was or was not asked.
            models.Index(fields=["team_id", "owner"], name="stamphog_routing_owner"),
        ]

    def __str__(self) -> str:
        return f"{self.owner} {self.outcome} ({self.reason})"
