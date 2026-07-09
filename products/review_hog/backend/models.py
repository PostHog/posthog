from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.review_hog.backend.reviewer.artefact_content import (
    ArtefactContentValidationError,
    ReviewArtefactContent,
    ReviewIssueFinding,
    ReviewLogArtefactContent,
    ReviewWorkingStateContent,
    TaskRunArtefact,
    ValidationVerdict,
    artefact_type_for,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution


class ReviewReport(UUIDModel, TeamScopedRootMixin):
    """The living per-target review document.

    One row per `(team, repository, pr_number)` — or per `(team, repository, head_branch)` for a
    PR-less branch target (`pr_number` NULL), which upgrades in place once its PR exists. ReviewHog
    is loop-y — after the first pass it re-checks the target for new commits/comments and takes
    another turn — so the report is updated in place across turns and the watermark records what the
    latest turn already reviewed.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        IDLE = "idle"
        CLOSED = "closed"

    # db_constraint=False keeps the migration lock-free on hot posthog_team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    repository = models.CharField(max_length=255)  # owner/repo
    # NULL = a branch target with no PR yet; backfilled by the fetch stage once a PR opens.
    pr_number = models.IntegerField(null=True, blank=True)
    pr_url = models.TextField(blank=True)
    head_branch = models.CharField(max_length=255)
    base_branch = models.CharField(max_length=255)
    # Whose configuration drives this report's reviews (the PR author on the label path) — stamped at
    # acting-user resolve on every run, so it works for future non-PR triggers too. Powers "your
    # recent reviews"; db_constraint=False keeps the migration lock-free on hot posthog_user.
    acting_user = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    run_count = models.IntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    # Watermark — what the latest turn already reviewed, so a re-run knows what changed.
    head_sha = models.CharField(max_length=64, null=True, blank=True)
    # The head the latest COMPLETED turn reviewed — stamped at finalize, while `head_sha` advances at
    # turn START. Read paths pairing stats/links with the completed turn's findings anchor here, so an
    # in-flight or crashed turn's metadata never splices onto the previous turn's findings.
    completed_head_sha = models.CharField(max_length=64, null=True, blank=True)
    # Idempotency watermark — the head the review was last *published* to GitHub for (distinct from
    # `head_sha`, what was reviewed). Publishing skips when this equals the current head, so an
    # activity retry / re-trigger can't double-post the review or the one-time alpha promo comment.
    published_head_sha = models.CharField(max_length=64, null=True, blank=True)
    last_seen_comment_id = models.BigIntegerField(null=True, blank=True)
    report_markdown = models.TextField(default="", blank=True)
    # Provenance for inbox-triggered reviews: the signals report whose implementation this review
    # targets. A plain UUID, not an FK — the link must survive report deletion/reingestion on the
    # signals side (the signals-side `code_review` artefact is API-deletable; this row is the durable
    # link). Filled once, never overwritten by later turns from another trigger.
    signal_report_id = models.UUIDField(null=True, blank=True)
    # Which trigger created this report ("label" / "inbox" / "manual"); stamped on create only.
    trigger_source = models.CharField(max_length=20, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "repository", "pr_number"],
                name="unique_review_report_per_pr",
                condition=models.Q(pr_number__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["team", "repository", "head_branch"],
                name="unique_review_report_per_branch",
                condition=models.Q(pr_number__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status"], name="reviewhog_rpt_team_status_idx"),
            models.Index(fields=["signal_report_id"], name="reviewhog_rpt_signal_rpt_idx"),
            # Serves the "recent reviews" API: one user's reports, newest completed turn first.
            models.Index(fields=["team", "acting_user", "-last_run_at"], name="reviewhog_rpt_recent_idx"),
        ]


class ReviewReportArtefact(UUIDModel, TeamScopedRootMixin):
    """Append-only work log for a `ReviewReport`.

    Mirrors Signals' `SignalReportArtefact` funnel — the row's type is derived from the content
    model's class and attribution maps to `created_by` / `task` columns — but owns its own types
    and has no auto-start side effects.
    """

    class ArtefactType(models.TextChoices):
        ISSUE_FINDING = "issue_finding"
        VALIDATION_VERDICT = "validation_verdict"
        TASK_RUN = "task_run"
        COMMIT = "commit"
        CODE_REFERENCE = "code_reference"
        NOTE = "note"
        # Per-turn pipeline working state, read back by the DB-driven resume (head_sha-scoped).
        CHUNK_SET = "chunk_set"
        PERSPECTIVE_SELECTION = "perspective_selection"
        PERSPECTIVE_RESULT = "perspective_result"
        # The turn's fetched PR inputs, stored by reference so stage activities reload them from the
        # DB instead of crossing the Temporal workflow boundary with the big pr_files payload.
        PR_SNAPSHOT = "pr_snapshot"

    # Log types accumulate (each call is a new row). Findings and verdicts also append, but their
    # identity is `issue_key` — latest row per key wins at read time — so they get dedicated
    # appenders rather than going through `add_log`.
    LOG_ARTEFACT_TYPES: frozenset[str] = frozenset(
        {ArtefactType.TASK_RUN, ArtefactType.COMMIT, ArtefactType.CODE_REFERENCE, ArtefactType.NOTE}
    )
    # Working-state types accumulate per turn; the resume reads the latest per (head_sha, key).
    WORKING_STATE_ARTEFACT_TYPES: frozenset[str] = frozenset(
        {
            ArtefactType.CHUNK_SET,
            ArtefactType.PERSPECTIVE_SELECTION,
            ArtefactType.PERSPECTIVE_RESULT,
            ArtefactType.PR_SNAPSHOT,
        }
    )

    # db_constraint=False keeps the migration lock-free on hot posthog_team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    report = models.ForeignKey(ReviewReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=ArtefactType)
    content = models.TextField()
    # Turn scope, denormalized from content.head_sha so resume loaders can filter in SQL instead of
    # parsing every historical row. Null when the content model carries no head_sha.
    head_sha = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    # Attribution: exactly one of (created_by, task) is set on new rows, enforced at the write
    # helpers via `ArtefactAttribution`. SET_NULL so deleting a user/task degrades attribution to
    # "system/unknown" rather than destroying the report's work log. db_constraint=False keeps the
    # migration lock-free on hot posthog_user.
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    task = models.ForeignKey("tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        indexes = [
            models.Index(fields=["report"], name="reviewhog_art_report_idx"),
            models.Index(fields=["report", "type"], name="reviewhog_art_rpt_type_idx"),
            # Latest-wins seeks: WHERE report=? AND type=? ORDER BY created_at DESC.
            models.Index(fields=["report", "type", "-created_at"], name="reviewhog_art_rpt_type_ct_idx"),
        ]

    @classmethod
    def _create(
        cls,
        *,
        team_id: int,
        report_id: str,
        content: ReviewArtefactContent,
        attribution: ArtefactAttribution,
    ) -> "ReviewReportArtefact":
        """Single write funnel: derive the row's type from the content model's class, map
        attribution to columns, and insert.

        Goes through `for_team` so it works outside request context (the cloud/Temporal
        orchestrator has no ambient team scope, and the fail-closed manager would otherwise raise).
        """
        # A task_run's content.task_id is the same association as the row's `task` FK — they must
        # not diverge. The FK comes from attribution, so require task attribution that matches.
        if isinstance(content, TaskRunArtefact) and content.task_id != attribution.task_id:
            raise ArtefactContentValidationError("task_run content.task_id must match the artefact's attributed task")
        return cls.objects.for_team(team_id).create(
            team_id=team_id,
            report_id=report_id,
            type=artefact_type_for(content),
            content=content.model_dump_json(),
            head_sha=getattr(content, "head_sha", None),
            created_by_id=attribution.user_id,
            task_id=attribution.task_id,
        )

    @classmethod
    def append_finding(
        cls, *, team_id: int, report_id: str, content: ReviewIssueFinding, attribution: ArtefactAttribution
    ) -> "ReviewReportArtefact":
        """Append an `issue_finding` (latest row per `issue_key` wins at read time)."""
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    @classmethod
    def append_verdict(
        cls, *, team_id: int, report_id: str, content: ValidationVerdict, attribution: ArtefactAttribution
    ) -> "ReviewReportArtefact":
        """Append a `validation_verdict` (latest verdict per `issue_key` wins at read time)."""
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    @classmethod
    def add_log(
        cls, *, team_id: int, report_id: str, content: ReviewLogArtefactContent, attribution: ArtefactAttribution
    ) -> "ReviewReportArtefact":
        """Append a work-log entry (`task_run` / `commit` / `code_reference` / `note`); these accumulate."""
        if artefact_type_for(content) not in cls.LOG_ARTEFACT_TYPES:
            raise ValueError(f"{type(content).__name__} is not a log artefact content model")
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    @classmethod
    def add_working_state(
        cls, *, team_id: int, report_id: str, content: ReviewWorkingStateContent, attribution: ArtefactAttribution
    ) -> "ReviewReportArtefact":
        """Append per-turn pipeline working state (`chunk_set` / `perspective_result` / `pr_snapshot`).

        These accumulate; the DB-driven resume reads the latest row per (head_sha, key), so a
        resumed turn reuses completed sandbox work instead of re-running it.
        """
        if artefact_type_for(content) not in cls.WORKING_STATE_ARTEFACT_TYPES:
            raise ValueError(f"{type(content).__name__} is not a working-state artefact content model")
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)


class ReviewSkillConfig(UUIDModel, TeamScopedRootMixin):
    """Per-(team, user, review-skill) enablement for ReviewHog.

    One generic table for which review skills run for a user, discriminated by the skill-name prefix:
    `review-hog-perspective-*` (the review perspectives — **multi-enable**, ≥1 must stay on), plus
    `review-hog-validation-*` (the validator) and `review-hog-blind-spots-*` (the blind-spot check) —
    both **single-active**: exactly one runs, the select endpoint flips the others off, falling back to
    the canonical default when none is set. `enabled=True` means "active for this user" in every case;
    the cardinality rules are enforced in app code, not the DB, the same way the perspective min-1
    floor is.

    A skill is any team `LLMSkill` carrying the prefix (canonical or custom — handled identically);
    canonicals auto-seed on first resolve, customs are switched on via the config API. The skill itself
    stays team-level; this row only gates whether it runs for this user's PRs. Mirrors Signals'
    `SignalScoutConfig` enable/disable, minus the schedule — ReviewHog is PR-triggered, not on a clock.
    `skill_name` is the identity (mirrors scouts keying on it, never `created_by`).
    """

    # db_constraint=False keeps the migration lock-free on hot posthog_team / posthog_user.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    skill_name = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True, db_default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user", "skill_name"], name="uniq_review_skill_config_per_user"),
        ]
        indexes = [
            # The loaders seek WHERE team=? AND user=? AND enabled=true to resolve a run's skills.
            models.Index(fields=["team", "user", "enabled"], name="reviewhog_skillcfg_lookup_idx"),
        ]


class ReviewUserSettings(UUIDModel, TeamScopedRootMixin):
    """Per-(team, user) ReviewHog settings: what gets reviewed and how strict publishing is.

    One row per user per project, created with defaults on first read. `review_labeled_prs` is the
    label trigger's opt-out — the workflow gates on the PR author's row (no row = the defaults).
    `urgency_threshold` is the minimum priority a validated finding needs to be published; it snaps
    to a run at acting-user resolution, so mid-run edits don't flip gates between body and publish.
    `review_inbox_prs` is the inbox trigger's opt-in (default off — the budget gate for 100%-coverage
    cost): checked cheaply at the TaskRun-completion receiver and re-checked off the resolve snapshot.
    """

    class UrgencyThreshold(models.TextChoices):
        # Values mirror `IssuePriority` so the threshold compares directly against finding priorities.
        CONSIDER = "consider"  # "All issues"
        SHOULD_FIX = "should_fix"
        MUST_FIX = "must_fix"

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on the parents (app-level enforcement only).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    review_inbox_prs = models.BooleanField(default=False, db_default=False)
    review_labeled_prs = models.BooleanField(default=True, db_default=True)
    urgency_threshold = models.CharField(
        max_length=20,
        choices=UrgencyThreshold.choices,
        default=UrgencyThreshold.SHOULD_FIX,
        db_default=UrgencyThreshold.SHOULD_FIX.value,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="uniq_review_user_settings_per_user"),
        ]

    @classmethod
    def load(cls, team_id: int, user_id: int) -> "ReviewUserSettings":
        """The user's settings row, or an unsaved instance carrying the defaults when none exists."""
        row = cls.objects.for_team(team_id).filter(user_id=user_id).first()
        return row if row is not None else cls(team_id=team_id, user_id=user_id)
