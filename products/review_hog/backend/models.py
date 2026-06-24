from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.review_hog.backend.reviewer.artefact_content import (
    ArtefactContentValidationError,
    ReviewArtefactContent,
    ReviewIssueFinding,
    ReviewLogArtefactContent,
    TaskRunArtefact,
    ValidationVerdict,
    artefact_type_for,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution


class ReviewReport(UUIDModel, TeamScopedRootMixin):
    """The living per-PR review document.

    One row per `(team, repository, pr_number)`. ReviewHog is loop-y — after the first pass it
    re-checks the PR for new commits/comments and takes another turn — so the report is updated
    in place across turns and the watermark records what the latest turn already reviewed.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        IDLE = "idle"
        CLOSED = "closed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    repository = models.CharField(max_length=255)  # owner/repo
    pr_number = models.IntegerField()
    pr_url = models.TextField()
    head_branch = models.CharField(max_length=255)
    base_branch = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status, default=Status.ACTIVE)
    run_count = models.IntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    # Watermark — what the latest turn already reviewed, so a re-run knows what changed.
    head_sha = models.CharField(max_length=64, null=True, blank=True)
    last_seen_comment_id = models.BigIntegerField(null=True, blank=True)
    report_markdown = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "repository", "pr_number"], name="unique_review_report_per_pr"),
        ]
        indexes = [
            models.Index(fields=["team", "status"], name="reviewhog_rpt_team_status_idx"),
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

    # Log types accumulate (each call is a new row). Findings and verdicts also append, but their
    # identity is `issue_key` — latest row per key wins at read time — so they get dedicated
    # appenders rather than going through `add_log`.
    LOG_ARTEFACT_TYPES: frozenset[str] = frozenset(
        {ArtefactType.TASK_RUN, ArtefactType.COMMIT, ArtefactType.CODE_REFERENCE, ArtefactType.NOTE}
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    report = models.ForeignKey(ReviewReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=ArtefactType)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    # Attribution: exactly one of (created_by, task) is set on new rows, enforced at the write
    # helpers via `ArtefactAttribution`. SET_NULL so deleting a user/task degrades attribution to
    # "system/unknown" rather than destroying the report's work log.
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
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
