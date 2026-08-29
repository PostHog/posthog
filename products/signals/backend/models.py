import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, cast

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from django.utils.functional import Promise

from asgiref.sync import async_to_sync
from django_deprecate_fields import deprecate_field
from pydantic import ValidationError

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.extensions import register_team_extension_signal
from posthog.models.utils import UUIDModel

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContent,
    ArtefactContentValidationError,
    ChannelAssignment,
    Dismissal,
    LogArtefactContent,
    RelatedTo,
    SignalFinding,
    StatusArtefactContent,
    TaskRunArtefact,
    artefact_type_for,
    parse_artefact_content,
    task_run_identifier_for_legacy_relationship,
)
from products.signals.backend.enums import SignalSourceProduct, signal_source_product_choices

logger = logging.getLogger(__name__)


def signal_source_type_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(SignalSourceConfig.SourceType.choices)


class SignalSourceConfig(UUIDModel):
    # Source-product taxonomy is owned by products.signals.backend.enums (the same StrEnum the payload
    # contracts and frontend codegen use). Aliased here so `SignalSourceConfig.SourceProduct.X` keeps
    # working; choices are frozen-equivalent to the prior nested TextChoices, so no migration is needed.
    SourceProduct = SignalSourceProduct

    # Source-type choices are intentionally a *subset* of the full SignalSourceType taxonomy: only the
    # types that carry a per-team config row live here. session_problem gates through another config.
    # evaluation is retired, and stays in the taxonomy only so old signals still resolve to a label.
    # Every source_type the emission registry emits must appear here, or enabling that source 400s.
    class SourceType(models.TextChoices):
        SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster", "Session analysis cluster"
        EVALUATION_REPORT = "evaluation_report", "Evaluation report"
        ISSUE = "issue", "Issue"
        TICKET = "ticket", "Ticket"
        ISSUE_CREATED = "issue_created", "Issue created"
        ISSUE_REOPENED = "issue_reopened", "Issue reopened"
        ISSUE_SPIKING = "issue_spiking", "Issue spiking"
        CROSS_SOURCE_ISSUE = "cross_source_issue", "Cross source issue"
        ALERT_STATE_CHANGE = "alert_state_change", "Alert state change"
        HEALTH_ISSUE = "health_issue", "Health issue"
        ENDPOINT_EXECUTION_FAILED = "endpoint_execution_failed", "Endpoint execution failed"
        ENDPOINT_BREAKDOWN_LIMIT_EXCEEDED = "endpoint_breakdown_limit_exceeded", "Endpoint breakdown limit exceeded"
        SCANNER_FINDING = "scanner_finding", "Scanner finding"
        ANOMALY_INVESTIGATION = "anomaly_investigation", "Anomaly investigation"
        FEEDBACK = "feedback", "Feedback"
        REVIEW = "review", "Review"
        CI_FLAKY_CHECK = "ci_flaky_check", "CI flaky check"
        CI_BROKEN_DEFAULT_BRANCH = "ci_broken_default_branch", "CI broken default branch"
        CI_DURATION_REGRESSION = "ci_duration_regression", "CI duration regression"
        SEARCH_OPPORTUNITY = "search_opportunity", "Search opportunity"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="signal_source_configs")
    source_product = models.CharField(max_length=100, choices=signal_source_product_choices)
    source_type = models.CharField(max_length=100, choices=signal_source_type_choices)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    @classmethod
    def is_source_enabled(cls, team_id: int, source_product: str, source_type: str) -> bool:
        """Check whether a given signal source is enabled for a team.

        Scout findings are on by default (see below). For everything else, the team must have a
        SignalSourceConfig row with enabled=True.
        """
        # Replay Vision scanners are self-authorizing: the scanner's `emits_signals` flag is the
        # per-source config, so there's no separate SignalSourceConfig row to gate against.
        if source_product == cls.SourceProduct.REPLAY_VISION and source_type == cls.SourceType.SCANNER_FINDING:
            return True

        # Scout findings surface to the inbox by default — the team-level toggle was retired from the
        # UI, so this gate is fail-open: absence of a row means on. A team can still opt out via the
        # MCP/API by writing an explicit disabled row, which this honors.
        if source_product == cls.SourceProduct.SIGNALS_SCOUT and source_type == cls.SourceType.CROSS_SOURCE_ISSUE:
            return not cls.objects.filter(
                team_id=team_id,
                source_product=source_product,
                source_type=source_type,
                enabled=False,
            ).exists()

        # Session problem signals are emitted as part of session analysis,
        # so they're gated by the pre-existing session_analysis_cluster config
        if source_product == cls.SourceProduct.SESSION_REPLAY and source_type == "session_problem":
            source_type = cls.SourceType.SESSION_ANALYSIS_CLUSTER

        return cls.objects.filter(
            team_id=team_id,
            source_product=source_product,
            source_type=source_type,
            enabled=True,
        ).exists()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type"], name="unique_team_source_product_type"
            )
        ]


class AutonomyPriority(models.TextChoices):
    P0 = "P0", "P0"
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"
    P4 = "P4", "P4"


class SignalTeamConfig(ModelActivityMixin, UUIDModel):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_team_config",
    )
    # Master switch for autonomous inbox PRs. Null means the team never set it (autostart stays on
    # by default); only an explicit False disables it, leaving reports to still generate and notify
    # while the team reviews and opens PRs manually.
    autostart_enabled = models.BooleanField(null=True, blank=True)
    default_autostart_priority = models.CharField(max_length=2, choices=AutonomyPriority, default=AutonomyPriority.P4)
    default_slack_notification_channel = models.CharField(max_length=255, null=True, blank=True)
    autostart_base_branches = models.JSONField(default=dict, blank=True)
    # Daily cap on reports surfacing to the inbox, counted against SignalReport.first_visible_at
    # within the project-timezone day. Once reached, the whole generation pipeline pauses until
    # local midnight (see daily_limit.py). Null means unlimited.
    max_reports_per_day = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal team config"
        verbose_name_plural = "Signal team configs"

    def base_branch_for(self, repository: str | None) -> str | None:
        """Configured base branch for ``repository`` ("organization/repository"), if any.

        Keys are stored lowercased by the serializer, so the lookup lowercases to match.
        Every path that opens a self-driving pull request resolves through here, so that
        auto-start and the inbox "Create PR" button cannot disagree on the branch.
        """
        if not repository or not isinstance(self.autostart_base_branches, dict):
            return None
        return self.autostart_base_branches.get(repository.lower()) or None


register_team_extension_signal(SignalTeamConfig, logger=logger)


class SignalUserAutonomyConfig(UUIDModel):
    user = models.OneToOneField("posthog.User", on_delete=models.CASCADE, related_name="signal_autonomy_config")
    autostart_priority = models.CharField(max_length=2, choices=AutonomyPriority, null=True, blank=True)
    # Slack notifications for new inbox items where the user is a suggested reviewer.
    # All three fields are required together; a config row with any of them null
    # disables notifications. Integration is team-scoped, so notifications are
    # scoped to a single team via the integration's team.
    slack_notification_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    slack_notification_channel = models.CharField(max_length=255, null=True, blank=True)
    # When null, all priorities (including reports with no priority) notify.
    # When set, only reports with a priority at or above this value (P0 highest) notify.
    slack_notification_min_priority = models.CharField(max_length=2, choices=AutonomyPriority, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal user autonomy config"
        verbose_name_plural = "Signal user autonomy configs"


class InvalidStatusTransition(Exception):
    def __init__(self, from_status: str, to_status: str):
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Cannot transition from {from_status} to {to_status}")


class SignalReport(UUIDModel):
    class Status(models.TextChoices):
        POTENTIAL = "potential"
        CANDIDATE = "candidate"
        IN_PROGRESS = "in_progress"
        PENDING_INPUT = "pending_input"
        READY = "ready"
        RESOLVED = "resolved"
        FAILED = "failed"
        DELETED = "deleted"
        SUPPRESSED = "suppressed"

    class BillingExemptReason(models.TextChoices):
        POSTHOG_HEALTH_CHECK = "posthog_health_check", "PostHog health check"
        POSTHOG_ONBOARDING = "posthog_onboarding", "PostHog onboarding"
        POSTHOG_SYSTEM = "posthog_system", "PostHog system"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status, default=Status.POTENTIAL)
    # System billing exemption: non-null means this report's implementation PRs must never be
    # charged (PostHog-system origins, e.g. health-check scout findings). Prospective-only —
    # set via `billing.mark_report_billing_exempt` while no billable PR run exists, and never
    # flipped afterwards, so no usage report can observe the value changing. Null = billable.
    billing_exempt_reason = models.CharField(max_length=30, choices=BillingExemptReason, null=True, blank=True)
    # The status held immediately before the report was suppressed (archived). Lets "restore"
    # return the report to where it was instead of always dropping it back to POTENTIAL.
    # Null for reports that were never suppressed (and cleared again on restore).
    status_before_suppression = models.CharField(max_length=20, choices=Status, null=True, blank=True)

    total_weight = models.FloatField(default=0.0)
    signal_count = models.IntegerField(default=0)

    # Forward-looking promotion threshold: a potential report only promotes when signal_count >= this.
    # Incremented each summary run to prevent re-promoting on every signal.
    # The snooze action sets it to signal_count + N to delay re-promotion by N signals.
    signals_at_run = models.IntegerField(default=0)
    # How many times the summary workflow has run for this report (incremented on each CANDIDATE -> IN_PROGRESS).
    run_count = models.IntegerField(default=0)

    # LLM-generated during signal matching
    title = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    # The charts this report currently shows, each a `ReportChart` (see report_charts.py). Part of
    # the report's content rather than its artefact log: a chart illustrates the summary, so it is
    # replaced with the summary rather than accumulating versions beside it. `summary` places one
    # with a `[label](chart:<chart_id>)` link; the rest render below the prose.
    # `db_default` alongside `default`: a callable default is Python-only, so without it the column
    # lands NOT NULL with no Postgres default and any insert from a pre-deploy worker — which omits
    # the column it doesn't know about — fails until the rollout finishes.
    charts = models.JSONField(default=list, db_default=[], blank=True)
    # Questions this report suggests its reader ask AI about it, each a plain string (see
    # report_prompts.py). Content rather than log for the same reason `charts` is: a question is
    # written against the summary it sits under, so a rewrite of that summary replaces it instead of
    # leaving a stale question beside fresh prose. The inbox offers them above the "Ask AI" box.
    # `db_default` alongside `default` for the reason spelled out on `charts`.
    suggested_prompts = models.JSONField(default=list, db_default=[], blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    # When the report first became user-visible (entered READY or PENDING_INPUT, the statuses the
    # inbox lists). Set once and never cleared, so re-research and suppress/restore cycles don't
    # recount it against SignalTeamConfig.max_reports_per_day. Null for reports that predate the
    # field or never surfaced.
    first_visible_at = models.DateTimeField(null=True, blank=True)

    # Video segment clustering fields
    cluster_centroid = deprecate_field(
        ArrayField(
            base_field=models.FloatField(),
            blank=True,
            null=True,
            help_text="Embedding centroid for this report's video segment cluster",
        )
    )
    cluster_centroid_updated_at = deprecate_field(models.DateTimeField(blank=True, null=True))
    # Deprecated - unused
    conversation = deprecate_field(
        models.ForeignKey("posthog_ai.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    )
    relevant_user_count = deprecate_field(models.IntegerField(blank=True, null=True))

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "promoted_at"]),
            models.Index(fields=["team", "created_at"]),
            # Partial: the daily-limit gate only ever counts stamped rows for one team and day.
            models.Index(
                fields=["team", "first_visible_at"],
                condition=models.Q(first_visible_at__isnull=False),
                name="signals_report_first_visible",
            ),
        ]

    def transition_to(
        self,
        new_status: "SignalReport.Status",
        *,
        snooze_for: int | None = None,
        signals_at_run_increment: int | None = None,
        reset_weight: bool = False,
        title: str | None = None,
        summary: str | None = None,
        error: str | None = None,
    ) -> list[str]:
        """
        Validate and apply a status transition with side effects.
        Returns the list of fields that were modified.

        Raises InvalidStatusTransition if the transition is not allowed.
        Does NOT call .save().
        """
        S = self.Status
        updated_fields: set[str] = set()

        match (self.status, new_status):
            # Pipeline transitions
            # - POTENTIAL -> CANDIDATE when the report is selected for summary generation
            # - READY -> CANDIDATE when new matching signals reopen the report for summary / agentic
            #   research. RESOLVED is terminal and never reopens: a recurring issue starts a fresh
            #   report, linked to the resolved one via related_to artefacts (see
            #   assign_and_emit_signal_activity).
            case (S.POTENTIAL | S.READY, S.CANDIDATE):
                self.promoted_at = timezone.now()
                updated_fields.add("promoted_at")

            case (S.CANDIDATE, S.IN_PROGRESS):
                if signals_at_run_increment is None:
                    raise ValueError("signals_at_run_increment is required for candidate -> in_progress")
                self.last_run_at = timezone.now()
                self.signals_at_run = self.signal_count + signals_at_run_increment
                self.run_count += 1
                updated_fields.update(["last_run_at", "signals_at_run", "run_count"])

            # A summary run paused mid-workflow by the self-driving credits quota gate returns to
            # CANDIDATE, so the report re-promotes on the next matching signal instead of sticking
            # in IN_PROGRESS (which no promotion rule ever picks up). No side effects: promoted_at
            # is still accurate, and run_count / signals_at_run keep the values the aborted run
            # advanced them to (run_count feeds Temporal workflow IDs and must never roll back).
            case (S.IN_PROGRESS, S.CANDIDATE):
                pass

            case (S.IN_PROGRESS, S.READY):
                if title is None or summary is None:
                    raise ValueError("title and summary are required for in_progress -> ready")
                self.title = title
                self.summary = summary
                self.error = None
                updated_fields.update(["title", "summary", "error"])

            case (S.IN_PROGRESS, S.PENDING_INPUT):
                if title is None or summary is None or error is None:
                    raise ValueError("title, summary, and error are required for in_progress -> pending_input")
                self.title = title
                self.summary = summary
                self.error = error
                updated_fields.update(["title", "summary", "error"])

            # Reset to potential (from in_progress via actionability judge, from suppressed, or by user snooze)
            case (S.IN_PROGRESS | S.PENDING_INPUT | S.SUPPRESSED | S.READY | S.RESOLVED | S.FAILED, S.POTENTIAL):
                self.promoted_at = None
                updated_fields.add("promoted_at")
                if self.status == S.SUPPRESSED:
                    self.status_before_suppression = None
                    updated_fields.add("status_before_suppression")
                if snooze_for is not None:
                    self.signals_at_run = self.signal_count + snooze_for
                    updated_fields.add("signals_at_run")
                if reset_weight:
                    self.total_weight = 0.0
                    updated_fields.add("total_weight")
                if error is not None:
                    self.error = error
                    updated_fields.add("error")

            # Restore (un-archive) a suppressed report to the researched, user-visible state it held
            # before suppression. Title/summary/error are already set from the earlier research run,
            # so they are preserved as-is. In-flight states (candidate/in_progress) are never restored
            # here — they have no live workflow to resume and instead route back through POTENTIAL above.
            case (S.SUPPRESSED, S.PENDING_INPUT | S.READY | S.RESOLVED | S.FAILED):
                self.status_before_suppression = None
                updated_fields.add("status_before_suppression")

            # Any non-deleted status can fail
            case (S.POTENTIAL | S.CANDIDATE | S.IN_PROGRESS | S.PENDING_INPUT | S.READY | S.RESOLVED, S.FAILED):
                if error is None:
                    raise ValueError("error is required for transition to failed")
                self.error = error
                updated_fields.add("error")

            # Any non-deleted status can be suppressed
            case (
                S.POTENTIAL | S.CANDIDATE | S.IN_PROGRESS | S.PENDING_INPUT | S.READY | S.RESOLVED | S.FAILED,
                S.SUPPRESSED,
            ):
                # Remember where it was so "restore" can return it there (see restore_target_status).
                self.status_before_suppression = self.status
                self.promoted_at = None
                updated_fields.update(["status_before_suppression", "promoted_at"])

            # Any non-deleted status can be deleted
            case (
                S.POTENTIAL
                | S.CANDIDATE
                | S.IN_PROGRESS
                | S.PENDING_INPUT
                | S.READY
                | S.RESOLVED
                | S.FAILED
                | S.SUPPRESSED,
                S.DELETED,
            ):
                pass

            # Only ready reports can resolve
            # Reports are marked resolved when the linked implementation PR is merged (see tasks GitHub webhook)
            case (S.PENDING_INPUT | S.READY, S.RESOLVED):
                # Just pass through to status setting
                pass

            case _:
                raise InvalidStatusTransition(self.status, new_status)

        # First arrival into a user-visible status (the inbox lists READY and PENDING_INPUT).
        # Set-once: re-research and suppress/restore cycles keep the original timestamp, so a
        # report only ever counts once toward SignalTeamConfig.max_reports_per_day.
        if new_status in (S.READY, S.PENDING_INPUT) and self.first_visible_at is None:
            self.first_visible_at = timezone.now()
            updated_fields.add("first_visible_at")

        self.status = new_status
        updated_fields.update(["status", "updated_at"])
        return list(updated_fields)

    def restore_target_status(self) -> "SignalReport.Status":
        """
        The status a suppressed report should return to on restore (un-archive).

        A report archived while fully researched (ready / pending_input / resolved / failed) returns
        to that exact state so it reappears where the user archived it from. Anything else — including
        in-flight states with no live workflow, or legacy rows with no recorded prior status — routes
        back through POTENTIAL to re-enter the pipeline.
        """
        S = self.Status
        researched = {S.READY, S.PENDING_INPUT, S.RESOLVED, S.FAILED}
        prior = self.status_before_suppression
        if prior in {s.value for s in researched}:
            return S(prior)
        return S.POTENTIAL

    def update_authored_content(self, *, title: str | None = None, summary: str | None = None) -> list[str]:
        """Rewrite an agent-authored report's `title`/`summary` in place, independent of status.

        The pipeline only ever sets title/summary as a side effect of the `IN_PROGRESS -> READY`
        (or `-> PENDING_INPUT`) transition — there is no path to edit them on an already-surfaced
        report. The scout report-authoring channel needs one: `emit_report` writes them at creation
        (a report born READY, not transitioned there) and `edit_report` rewrites them afterwards.

        Only the provided fields change; passing neither is a no-op. Returns the modified field names
        (with `updated_at`) for a targeted `save(update_fields=...)`; does NOT call `.save()` — the
        caller owns the write so it can batch this with other changes in one transaction.
        """
        updated_fields: set[str] = set()
        # Compared before assigning, so an idempotent re-send of the current text is a no-op. The REST
        # PATCH path already compares this way, and a spurious "changed" here would cost a needless
        # save, a misleading edit-history note, and a retracted embedding (see receivers.py).
        if title is not None and title != self.title:
            self.title = title
            updated_fields.add("title")
        if summary is not None and summary != self.summary:
            self.summary = summary
            updated_fields.add("summary")
        if updated_fields:
            updated_fields.add("updated_at")
        return list(updated_fields)

    @staticmethod
    def _merge_task_runs(
        artefact_rows: "list[tuple[datetime, str]]",
        report_task_rows: "list[tuple[datetime, str | None, Any]]",
        *,
        product: str | None,
        type: str | None,
    ) -> list[TaskRunArtefact]:
        """Merge `task_run` artefact contents with faked-from-`SignalReportTask` runs into one
        de-duplicated, oldest-first list — the view that would exist once the backfill has run.

        A `SignalReportTask` row is surfaced as the `task_run` artefact the backfill would create
        for it (same `(product, type)` mapping). De-dup is by `task_id` (mirroring the backfill,
        which skips a task that already has an artefact); when a task appears in both sources the
        real artefact wins, since on equal timestamps it is ordered first.
        """
        # (created_at, source_rank, run); source_rank 0 = real artefact, so it wins ties.
        candidates: list[tuple[datetime, int, TaskRunArtefact]] = []
        for created_at, content in artefact_rows:
            try:
                run = TaskRunArtefact.model_validate_json(content)
            except ValidationError:
                continue  # tolerate malformed legacy TextField content
            candidates.append((created_at, 0, run))
        for created_at, relationship, task_id in report_task_rows:
            run_product, run_type = task_run_identifier_for_legacy_relationship(relationship)
            candidates.append(
                (created_at, 1, TaskRunArtefact(task_id=str(task_id), run_id=None, product=run_product, type=run_type))
            )

        candidates = [
            c
            for c in candidates
            if (product is None or c[2].product == product) and (type is None or c[2].type == type)
        ]
        candidates.sort(key=lambda c: (c[0], c[1]))

        seen: set[str] = set()
        result: list[TaskRunArtefact] = []
        for _created_at, _rank, run in candidates:
            if run.task_id in seen:
                continue
            seen.add(run.task_id)
            result.append(run)
        return result

    @classmethod
    def associated_task_runs(
        cls, *, report_id: str, team_id: int | None = None, product: str | None = None, type: str | None = None
    ) -> list[TaskRunArtefact]:
        """The task runs associated with a report, unified across the `task_run` artefact log and the
        legacy `SignalReportTask` gate rows and de-duplicated by task — the view you would get once
        `backfill_task_run_artefacts` has converted every gate row into a `task_run` artefact.

        Gate rows are surfaced as if they were `task_run` artefacts, so "does this report have an
        associated task (of a given product/type)?" is a single question against one artefact-shaped
        list — callers should not query `SignalReportArtefact` / `SignalReportTask` directly. Pass
        `product` / `type` to narrow (e.g. `product="signals", type="implementation"`).
        """
        artefacts = SignalReportArtefact.objects.filter(
            report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN
        )
        report_tasks = SignalReportTask.objects.filter(report_id=report_id)
        if team_id is not None:
            artefacts = artefacts.filter(team_id=team_id)
            report_tasks = report_tasks.filter(team_id=team_id)
        return cls._merge_task_runs(
            list(artefacts.values_list("created_at", "content")),
            list(report_tasks.values_list("created_at", "relationship", "task_id")),
            product=product,
            type=type,
        )

    @classmethod
    async def aassociated_task_runs(
        cls, *, report_id: str, team_id: int | None = None, product: str | None = None, type: str | None = None
    ) -> list[TaskRunArtefact]:
        """Async counterpart of `associated_task_runs`."""
        artefacts = SignalReportArtefact.objects.filter(
            report_id=report_id, type=SignalReportArtefact.ArtefactType.TASK_RUN
        )
        report_tasks = SignalReportTask.objects.filter(report_id=report_id)
        if team_id is not None:
            artefacts = artefacts.filter(team_id=team_id)
            report_tasks = report_tasks.filter(team_id=team_id)
        return cls._merge_task_runs(
            [row async for row in artefacts.values_list("created_at", "content")],
            [row async for row in report_tasks.values_list("created_at", "relationship", "task_id")],
            product=product,
            type=type,
        )

    @classmethod
    def associated_task_runs_for_reports(
        cls,
        *,
        report_ids: list[str],
        team_id: int | None = None,
        product: str | None = None,
        type: str | None = None,
    ) -> dict[str, list[TaskRunArtefact]]:
        """`associated_task_runs` batched over many reports — two queries total (one for the
        `task_run` artefacts, one for the legacy `SignalReportTask` gate rows) grouped by report in
        memory, rather than the 2N a per-report loop issues. Use this when resolving associations for
        a page of reports (e.g. the inbox list); per-report `associated_task_runs` is the N+1 trap.

        Returns `{report_id: runs}` with each report's runs identical to what `associated_task_runs`
        would return (oldest-first, de-duplicated by task). Reports with no associated runs are
        omitted, so callers can treat a missing key as "no runs".
        """
        if not report_ids:
            return {}

        artefacts = SignalReportArtefact.objects.filter(
            report_id__in=report_ids, type=SignalReportArtefact.ArtefactType.TASK_RUN
        )
        report_tasks = SignalReportTask.objects.filter(report_id__in=report_ids)
        if team_id is not None:
            artefacts = artefacts.filter(team_id=team_id)
            report_tasks = report_tasks.filter(team_id=team_id)

        artefact_rows_by_report: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
        for report_id, created_at, content in artefacts.values_list("report_id", "created_at", "content"):
            artefact_rows_by_report[str(report_id)].append((created_at, content))

        task_rows_by_report: dict[str, list[tuple[datetime, str | None, Any]]] = defaultdict(list)
        for report_id, created_at, relationship, task_id in report_tasks.values_list(
            "report_id", "created_at", "relationship", "task_id"
        ):
            task_rows_by_report[str(report_id)].append((created_at, relationship, task_id))

        result: dict[str, list[TaskRunArtefact]] = {}
        for report_id in {str(rid) for rid in report_ids}:
            runs = cls._merge_task_runs(
                artefact_rows_by_report.get(report_id, []),
                task_rows_by_report.get(report_id, []),
                product=product,
                type=type,
            )
            if runs:
                result[report_id] = runs
        return result

    @classmethod
    def synthetic_legacy_task_run_artefacts(
        cls, *, report_id: str, team_id: int, existing_artefacts: "list[SignalReportArtefact]"
    ) -> "list[SignalReportArtefact]":
        """Unsaved `task_run` artefacts standing in for legacy `SignalReportTask` rows whose task is
        not yet represented in the artefact log, so a report's research / implementation /
        repo-selection associations surface in the artefact list even before
        `backfill_task_run_artefacts` has converted its gate rows.

        De-duplicated by task against the `task_run` artefacts already in `existing_artefacts` (a
        real row always wins); each synthetic row borrows its `SignalReportTask` id and `created_at`
        so it is stable across polls and chronologically correct, and applies the same
        `(product, type)` mapping the backfill would. Never saved — the backfill is what persists
        them for real; this is the read-time view of that union (the row-level counterpart of
        `associated_task_runs`).
        """
        seen_task_ids: set[str] = set()
        for artefact in existing_artefacts:
            if artefact.type != SignalReportArtefact.ArtefactType.TASK_RUN:
                continue
            try:
                seen_task_ids.add(TaskRunArtefact.model_validate_json(artefact.content).task_id)
            except ValidationError:
                continue

        synthetic: list[SignalReportArtefact] = []
        report_tasks = SignalReportTask.objects.filter(report_id=report_id, team_id=team_id).order_by("created_at")
        for report_task in report_tasks:
            task_id = str(report_task.task_id)
            if task_id in seen_task_ids:
                continue
            seen_task_ids.add(task_id)
            product, run_type = task_run_identifier_for_legacy_relationship(report_task.relationship)
            synthetic.append(
                SignalReportArtefact(
                    id=report_task.id,
                    team_id=team_id,
                    report_id=report_id,
                    type=SignalReportArtefact.ArtefactType.TASK_RUN,
                    content=TaskRunArtefact(
                        task_id=task_id, run_id=None, product=product, type=run_type
                    ).model_dump_json(),
                    created_at=report_task.created_at,
                    task_id=report_task.task_id,
                )
            )
        return synthetic

    @staticmethod
    def associated_task_runs_filter(report_ref: Any) -> "models.Q":
        """A `Q` matching `tasks.TaskRun`s whose task is associated with the correlated report,
        unified across the `task_run` artefact log and the legacy `SignalReportTask` gate rows —
        the SQL-level counterpart of `associated_task_runs`, for embedding in a queryset
        annotation/filter (e.g. via `tasks` facade subquery helpers) so report→task correlation
        stays in one query instead of N per-report calls.

        `report_ref` is the report-id expression at the nesting depth where the `Q` is embedded —
        inside the facade's `TaskRun` subquery that is one level below the report queryset, so
        `OuterRef(OuterRef("id"))`. Unfiltered by `(product, type)`: those discriminators live in
        the artefact's JSON content, which we deliberately don't cast in SQL — the caller's own run
        filter (e.g. a non-empty `output.pr_url`, which only implementation runs produce) supplies
        the specificity.
        """
        artefact_task_ids = SignalReportArtefact.objects.filter(
            report_id=report_ref, type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id__isnull=False
        ).values("task_id")
        legacy_task_ids = SignalReportTask.objects.filter(report_id=report_ref).values("task_id")
        return models.Q(task_id__in=artefact_task_ids) | models.Q(task_id__in=legacy_task_ids)

    @staticmethod
    def reports_for_task_filter(task_id: Any) -> "models.Q":
        """A `Q` on `SignalReport.id` matching the reports `task_id` is associated with, unified
        across the `task_run` artefact log and the legacy `SignalReportTask` gate rows — the
        reverse-direction (task → reports) counterpart of `associated_task_runs_filter`, for
        embedding in a `SignalReport` queryset filter.

        Both subqueries seek the indexed `task_id` FK column (artefact + gate row), so this stays a
        couple of index lookups regardless of how many artefacts a report accumulates.
        """
        artefact_report_ids = SignalReportArtefact.objects.filter(
            type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id=task_id
        ).values("report_id")
        legacy_report_ids = SignalReportTask.objects.filter(task_id=task_id).values("report_id")
        return models.Q(id__in=artefact_report_ids) | models.Q(id__in=legacy_report_ids)

    @staticmethod
    def reports_for_task_ids_filter(task_ids: Any) -> "models.Q":
        """`reports_for_task_filter` widened to a *set* of tasks: a `Q` on `SignalReport.id` matching
        the reports associated with any task in `task_ids` (a collection or, preferably, a `task_id`
        subquery), unified across the `task_run` artefact log and the legacy `SignalReportTask` gate
        rows.

        Lets a per-report correlated `Exists` over `tasks.TaskRun` be *decorrelated*: drive off the
        small task set (e.g. tasks that produced a PR) and map it to reports here via the indexed
        `task_id` columns, instead of probing the runs once per candidate report.
        """
        artefact_report_ids = SignalReportArtefact.objects.filter(
            type=SignalReportArtefact.ArtefactType.TASK_RUN, task_id__in=task_ids
        ).values("report_id")
        legacy_report_ids = SignalReportTask.objects.filter(task_id__in=task_ids).values("report_id")
        return models.Q(id__in=artefact_report_ids) | models.Q(id__in=legacy_report_ids)


class SignalEmissionRecord(UUIDModel):
    """Tracks which source records have been emitted as signals.

    Owned by the signals app so source models (e.g. Ticket) stay decoupled.
    One row per source record, upserted on emission.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    source_product = models.CharField(max_length=100)
    source_type = models.CharField(max_length=100)
    source_id = models.CharField(max_length=200)
    emitted_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_product", "source_type", "source_id"],
                name="unique_signal_emission_record",
            )
        ]
        indexes = [
            models.Index(
                fields=["team", "source_product", "source_type"],
                name="signals_emission_lookup_idx",
            )
        ]


def signal_report_artefact_type_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(SignalReportArtefact.ArtefactType.choices)


class SignalReportArtefact(UUIDModel):
    class ArtefactType(models.TextChoices):
        VIDEO_SEGMENT = "video_segment"
        SAFETY_JUDGMENT = "safety_judgment"
        ACTIONABILITY_JUDGMENT = "actionability_judgment"
        PRIORITY_JUDGMENT = "priority_judgment"
        SIGNAL_FINDING = "signal_finding"
        REPO_SELECTION = "repo_selection"
        SUGGESTED_REVIEWERS = "suggested_reviewers"
        CHANNEL_ASSIGNMENT = "channel_assignment"
        DISMISSAL = "dismissal"
        CODE_REFERENCE = "code_reference"
        COMMIT = "commit"
        TASK_RUN = "task_run"
        NOTE = "note"
        TITLE_CHANGE = "title_change"
        SUMMARY_CHANGE = "summary_change"
        CODE_REVIEW = "code_review"
        RELATED_TO = "related_to"

    # Every artefact is an append-only, point-in-time log entry — nothing is mutated in place by
    # the producers. The two sets below classify *what an entry means*, not how it is written:
    #   - status artefacts describe the report's current state (judgments, repo selection,
    #     suggested reviewers, channel assignments). They are appended on each change; the
    #     report's *current* status is the latest row of that type by `created_at` (the serializer
    #     derives priority/actionability/reviewers with `order_by("-created_at")[:1]` subqueries).
    #   - log artefacts record discrete work done on a report (code references, commits,
    #     task runs, notes, and title/summary edits). Appended via `add_log`.
    # `signal_finding` is appended too, but its logical identity is `(report, content.signal_id)`:
    # a new signal yields a new entry, re-researching an existing signal appends a new version
    # (latest per signal_id wins). It is intentionally in neither set.
    STATUS_ARTEFACT_TYPES: frozenset[str] = frozenset(
        {
            ArtefactType.SAFETY_JUDGMENT,
            ArtefactType.ACTIONABILITY_JUDGMENT,
            ArtefactType.PRIORITY_JUDGMENT,
            ArtefactType.REPO_SELECTION,
            ArtefactType.SUGGESTED_REVIEWERS,
            ArtefactType.CHANNEL_ASSIGNMENT,
        }
    )
    LOG_ARTEFACT_TYPES: frozenset[str] = frozenset(
        {
            ArtefactType.CODE_REFERENCE,
            ArtefactType.COMMIT,
            ArtefactType.TASK_RUN,
            ArtefactType.NOTE,
            ArtefactType.TITLE_CHANGE,
            ArtefactType.SUMMARY_CHANGE,
            ArtefactType.CODE_REVIEW,
            ArtefactType.RELATED_TO,
        }
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=signal_report_artefact_type_choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    # Nullable so the migration is a fast, rolling-deploy-safe `ADD COLUMN ... NULL`; `auto_now`
    # populates it on every subsequent save, so existing rows fill in the next time they change.
    updated_at = models.DateTimeField(auto_now=True, null=True)
    # Attribution: who produced this artefact. Exactly one of (created_by, task) is set on new
    # rows — enforced at the write helpers via `ArtefactAttribution`, not as a DB constraint,
    # because legacy rows (and explicit system writes) legitimately carry NULLs in both.
    # SET_NULL: deleting a user/task degrades attribution to "system/unknown" rather than
    # destroying the report's work log.
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    task = models.ForeignKey("tasks.Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    channel = models.ForeignKey(
        "tasks.Channel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )

    class Meta:
        indexes = [
            models.Index(fields=["report"], name="signals_sig_report__idx"),
            # For JOINs involving matching a report to artifact of a certain type
            models.Index(fields=["report", "type"], name="signals_sig_report_type_idx"),
            # Latest-wins lookups: artefacts are append-only, so deriving the current status / log
            # tail is `WHERE report=? AND type=? ORDER BY created_at DESC` — this makes it a seek.
            models.Index(fields=["report", "type", "-created_at"], name="signals_sig_rpt_type_ct_idx"),
            models.Index(fields=["channel"], name="signals_sig_channel_idx"),
        ]

    @classmethod
    def _create(
        cls,
        *,
        team_id: int,
        report_id: str,
        content: ArtefactContent,
        attribution: ArtefactAttribution,
    ) -> "SignalReportArtefact":
        """Single write funnel: derive the row's type from the content model's class, map
        attribution to columns, and insert. Content is a typed model (parsed at the API boundary
        or constructed directly), so a row's type can never mismatch its content shape and no row
        can be written unattributed.
        """
        # A task_run's content.task_id is the same association as the row's `task` FK — they must
        # not diverge. The FK comes from attribution, so require task attribution that matches.
        if isinstance(content, TaskRunArtefact) and content.task_id != attribution.task_id:
            raise ArtefactContentValidationError("task_run content.task_id must match the artefact's attributed task")
        return cls.objects.create(
            team_id=team_id,
            report_id=report_id,
            type=artefact_type_for(content),
            content=content.model_dump_json(),
            created_by_id=attribution.user_id,
            task_id=attribution.task_id,
            channel_id=content.channel_id if isinstance(content, ChannelAssignment) else None,
        )

    @classmethod
    def append_status(
        cls,
        *,
        team_id: int,
        report_id: str,
        content: StatusArtefactContent,
        attribution: ArtefactAttribution,
        reevaluate_autostart: bool = True,
    ) -> "SignalReportArtefact":
        """Append a new version of a status artefact (see `STATUS_ARTEFACT_TYPES`) and return it.

        Status artefacts are append-only: each (re)assessment creates a new row, and the report's
        current status is the latest row of that type (by `created_at`).

        Appending a `suggested_reviewers` status re-evaluates auto-start on commit (idempotent),
        since changing reviewers can newly satisfy it. Callers that orchestrate auto-start
        themselves with full in-hand context — the agentic pipeline / custom agents, which run on
        the async worker and call it directly — pass ``reevaluate_autostart=False``.
        """
        if artefact_type_for(content) not in cls.STATUS_ARTEFACT_TYPES:
            raise ValueError(f"{type(content).__name__} is not a status artefact content model")
        artefact = cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)
        if reevaluate_autostart and artefact.type == cls.ArtefactType.SUGGESTED_REVIEWERS:
            cls._schedule_autostart_reevaluation(team_id=team_id, report_id=str(report_id))
        return artefact

    @classmethod
    def append_finding(
        cls, *, team_id: int, report_id: str, content: SignalFinding, attribution: ArtefactAttribution
    ) -> "SignalReportArtefact":
        """Append a `signal_finding` artefact (one investigation result; latest per `signal_id` wins).

        `signal_finding` is neither a status nor a log type — it has its own identity keyed by the
        finding's `signal_id` — so it gets a dedicated appender rather than going through
        `append_status` / `add_log`.
        """
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    @classmethod
    def append_dismissal(
        cls, *, team_id: int, report_id: str, content: Dismissal, attribution: ArtefactAttribution
    ) -> "SignalReportArtefact":
        """Append a `dismissal` artefact (dismissal/snooze feedback; entries stack over time).

        `dismissal` is neither a status nor a log type — each dismissal is its own point-in-time
        record — so it gets a dedicated appender.
        """
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    @staticmethod
    def _schedule_autostart_reevaluation(*, team_id: int, report_id: str) -> None:
        """After the current transaction commits, re-evaluate auto-start for the report.

        Changing a report's suggested reviewers can newly satisfy auto-start (e.g. adding a
        reviewer whose autonomy threshold qualifies), so any path that appends a reviewers status
        re-runs the idempotent auto-start check. Scheduled on commit so the new reviewers are
        visible and the task-start side effect isn't rolled back; best-effort so it never breaks
        the write. Imported lazily to avoid a models <-> auto_start import cycle.
        """

        def _run() -> None:
            from products.signals.backend import auto_start

            try:
                async_to_sync(auto_start.maybe_autostart_from_report_artefacts)(team_id=team_id, report_id=report_id)
            except Exception:
                logger.exception(
                    "signals reviewer-change auto-start re-evaluation failed", extra={"report_id": report_id}
                )

        transaction.on_commit(_run)

    @classmethod
    def add_log(
        cls, *, team_id: int, report_id: str, content: LogArtefactContent, attribution: ArtefactAttribution
    ) -> "SignalReportArtefact":
        """Append a log artefact (see `LOG_ARTEFACT_TYPES`) to a report and return it.

        Log artefacts accumulate — each call creates a new row.

        `related_to` links are symmetric: writing A→B here also records B→A on the other report, so
        the link is maintained on the common write path and stays discoverable from either side. The
        reverse row goes through `_create` (not `add_log`) so it doesn't recurse.
        """
        if artefact_type_for(content) not in cls.LOG_ARTEFACT_TYPES:
            raise ValueError(f"{type(content).__name__} is not a log artefact content model")
        artefact = cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)
        if isinstance(content, RelatedTo):
            # Same team_id: reports link only within a team (grouping is per-team), so the reverse
            # row belongs to the same tenant.
            cls._create(
                team_id=team_id,
                report_id=content.report_id,
                content=RelatedTo(report_id=str(report_id)),
                attribution=attribution,
            )
        return artefact

    @classmethod
    def append(
        cls,
        *,
        team_id: int,
        report_id: str,
        content: ArtefactContent,
        attribution: ArtefactAttribution,
        reevaluate_autostart: bool = True,
    ) -> "SignalReportArtefact":
        """Append an artefact of any content model, routing to its type's append semantics.

        Status types are latest-wins (`append_status`), `signal_finding` is keyed by signal_id,
        `dismissal` entries stack, log types accumulate (`add_log`), and anything else
        (`video_segment`) is a plain append. This model-level helper accepts every content model —
        an agent can append a new status version just like the pipeline, and the newest row of a
        status type is the report's canonical status. (The HTTP write API additionally refuses
        legacy read-only types such as `video_segment` — see `NON_WRITABLE_ARTEFACT_TYPES`.)

        Log types route through `add_log` (not straight to `_create`) so its side effects — e.g. the
        symmetric `related_to` back-link — are maintained no matter which write path is used.
        """
        artefact_type = artefact_type_for(content)
        if artefact_type in cls.STATUS_ARTEFACT_TYPES:
            return cls.append_status(
                team_id=team_id,
                report_id=report_id,
                content=cast(StatusArtefactContent, content),
                attribution=attribution,
                reevaluate_autostart=reevaluate_autostart,
            )
        if artefact_type in cls.LOG_ARTEFACT_TYPES:
            return cls.add_log(
                team_id=team_id, report_id=report_id, content=cast(LogArtefactContent, content), attribution=attribution
            )
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    def update_content(self, content: str | dict | list) -> None:
        """Replace this artefact's content in place (bumps `updated_at`), parsed and validated
        against the row's type. Attribution is creation-time only — edits don't reassign it.

        Editing the latest `suggested_reviewers` row changes the report's canonical reviewers,
        so it re-evaluates auto-start the same way appending a new reviewers row does."""
        parsed = parse_artefact_content(self.type, content)
        # The `task` FK is the association and is creation-time only; an edit must not let
        # content.task_id drift away from it.
        if isinstance(parsed, TaskRunArtefact):
            if str(parsed.task_id) != str(self.task_id):
                raise ArtefactContentValidationError(
                    "task_run content.task_id must match the artefact's task and cannot be reassigned by editing"
                )
            # (product, type) is the run's purpose and feeds the per-report task cap, which counts
            # non-pipeline signals runs; letting an edit relabel a discussion as pipeline work
            # would free its slot in the count.
            existing = parse_artefact_content(self.type, self.content)
            if isinstance(existing, TaskRunArtefact) and (parsed.product, parsed.type) != (
                existing.product,
                existing.type,
            ):
                raise ArtefactContentValidationError(
                    "task_run content.product and content.type record what ran and cannot be changed by editing"
                )
        self.content = parsed.model_dump_json()
        update_fields = ["content", "updated_at"]
        if isinstance(parsed, ChannelAssignment):
            self.channel_id = parsed.channel_id
            update_fields.append("channel_id")
        self.save(update_fields=update_fields)
        if self.type == SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS:
            self._schedule_autostart_reevaluation(team_id=self.team_id, report_id=str(self.report_id))


class SignalReportTask(UUIDModel):
    """Legacy task↔report link. Still the auto-start idempotency gate (an `implementation` row),
    but being migrated out in favour of `task_run` artefacts.

    Auto-start and the manual start-task API write *both* a `relationship="implementation"` row
    here and a `task_run` artefact (`record_implementation_task`). The gate reads this table — see
    `auto_start.py` — because the artefact log is freeform and API-mutable and so can't be trusted
    for a spend-controlling decision. Once `backfill_task_run_artefacts` has converted every legacy
    row to a `task_run` artefact, the gate can switch to the artefact log and this table can be
    dropped. General task↔report association already lives only in artefacts; this table is kept
    solely for the implementation gate during that transition.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="report_tasks")
    task = models.ForeignKey("tasks.Task", on_delete=models.CASCADE, related_name="signal_report_tasks")
    # "implementation" for the rows the gate reads; legacy rows also carry "research" /
    # "repo_selection". Nullable because the brief link-only window allowed unlabelled rows; the
    # backfill maps those to default artefacts.
    relationship = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal report task"
        verbose_name_plural = "Signal report tasks"
        constraints = [
            models.UniqueConstraint(fields=["report", "task"], name="unique_signal_report_task"),
        ]
        indexes = [
            # Billing and PR-URL lookups traverse this bridge by report filtered on relationship.
            models.Index(fields=["report", "relationship"], name="signals_report_task_rel_idx"),
        ]


class SignalReportRefund(TeamScopedRootMixin, UUIDModel):
    """One refund per report, ever — the user-facing "Refund" on a billed implementation PR.

    The row freezes everything billing-relevant at refund time: the `billing_path` (decided once
    by the UTC-day rule in `billing.py`, never recomputed), the flat `credits` charge, the
    `pr_url` / `pr_run_created_at` snapshots that make eligibility auditable and the quota offset
    a pure indexed filter on this table, and the billing period bounds the refund was accepted
    in, which the credited-path sync reports to billing. The `report` OneToOne is the concurrency
    backstop — a racing second refund hits its unique constraint.
    """

    class Reason(models.TextChoices):
        PR_INCORRECT = "pr_incorrect", "PR incorrect"
        PR_NOT_USEFUL = "pr_not_useful", "PR not useful"
        DUPLICATE = "duplicate", "Duplicate"
        OTHER = "other", "Other"

    class BillingPath(models.TextChoices):
        # Refund landed on the same UTC day as the first billable PR run: the usage query simply
        # excludes the report, so billing never learns it existed.
        EXCLUDED = "excluded"
        # Refund landed later in the billing period: usage stays truthful and the billing service
        # issues a Stripe customer-balance credit via the dispute endpoint.
        CREDITED = "credited"

    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin stays fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling for Django framework internals
    # (admin changelist queryset, related-object access, prefetch_related) that must not
    # filter by team. `default_manager_name` routes `_default_manager` / `_base_manager`
    # there. Same pattern as ProductTeamModel — duplicated here because TeamScopedRootMixin
    # doesn't bake it in (most callers don't need it).
    all_teams = models.Manager()  # noqa: DJ012

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents (app-level enforcement only).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    # RESTRICT: hard-deleting a report must never silently destroy this financial record (it drives
    # the quota offset and refund audit). Team deletion still cascades in via the team FK above.
    report = models.OneToOneField(SignalReport, on_delete=models.RESTRICT, related_name="refund")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    # Required — the future step-2 refund judge consumes these.
    reason = models.CharField(max_length=20, choices=Reason)
    note = models.TextField(blank=True)
    billing_path = models.CharField(max_length=10, choices=BillingPath)
    # Snapshot of SIGNALS_CREDITS_PER_REPORT_WITH_PR at refund time.
    credits = models.IntegerField()
    pr_url = models.TextField()
    # The first billable PR run's created_at — the billable moment this refund reverses.
    pr_run_created_at = models.DateTimeField()
    # The org's billing period [start, end) the refund was accepted in, frozen at creation. The
    # credited-path sync sends these bounds so billing can compute the credit against the accepted
    # period even when the sync lands after rollover — recomputing bounds at sync time is exactly
    # the drift that loses the credit. Null only on rows created before these fields existed.
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    # Credited path only: what billing actually credited, written back by the sync task.
    # Null until billing responds ($0 is a legitimate synced outcome, e.g. free tier).
    credit_amount_usd = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    billing_synced_at = models.DateTimeField(null=True, blank=True)
    billing_sync_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal report refund"
        verbose_name_plural = "Signal report refunds"
        default_manager_name = "all_teams"
        indexes = [
            # The quota offset sums credited refunds per org billing period; this makes it a seek.
            models.Index(fields=["team", "billing_path", "pr_run_created_at"], name="signals_refund_path_idx"),
        ]


class SignalReportAction(TeamScopedRootMixin, UUIDModel):
    """One row per (report, user, action type): a person's lightweight interaction with a report.

    Heavier work on a report already leaves person-attributed `SignalReportArtefact` rows (notes,
    dismissals, commits); this table records the interactions too light to be artefacts — opening
    a report, rating it with the thumbs — which otherwise exist only as client-side analytics
    events the backend can never read. The scout inactivity sweep
    (`scout_harness/inactivity.py`) reads both feeds when judging whether a scout's output is
    consumed, and the rows are a durable per-person consumption record future ranking/learning
    can build on.

    Upsert semantics, not a log: one row per (report, user, type), with `count` and `last_at`
    advancing on repeats. The high-volume raw stream (every open, dwell time, rank) stays in
    analytics events; this row is the queryable server-side fact that the interaction happened,
    kept one-row-per-person so it can sit on the sweep's hot path.
    """

    class ActionType(models.TextChoices):
        # A person opened the report's detail view in the inbox UI.
        VIEW = "view"
        # The thumbs rating at the end of the report body ("Was this report useful?").
        FEEDBACK = "feedback"

    # See SignalReportRefund.all_teams for rationale.
    all_teams = models.Manager()  # noqa: DJ012

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents (app-level enforcement only).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="actions")
    # CASCADE, unlike the artefact log's SET_NULL: a row here is evidence that a specific person
    # interacted, so with the person gone it proves nothing and can go with them.
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    type = models.CharField(max_length=20, choices=ActionType)
    # Latest-wins detail about the interaction (e.g. the feedback row keeps the most recent
    # sentiment). Never required by readers — the row's existence is the fact that matters.
    metadata = models.JSONField(default=dict, blank=True)
    # Coarse repeat signal, not an exact ledger: bundled rating+note submissions and reordered
    # fire-and-forget requests can move it by one either way. Readers get "roughly how often",
    # never billing-grade counts.
    count = models.PositiveIntegerField(default=1)
    first_at = models.DateTimeField(auto_now_add=True)
    last_at = models.DateTimeField()

    class Meta:
        verbose_name = "Signal report action"
        verbose_name_plural = "Signal report actions"
        default_manager_name = "all_teams"
        constraints = [
            # Also the only index: the sweep's "which of these reports did a person touch since
            # <ts>?" resolves as per-report probes on this, and keeping `last_at` out of any index
            # leaves the hot repeat-view UPDATE eligible for HOT.
            models.UniqueConstraint(fields=["report", "user", "type"], name="signals_report_action_identity"),
        ]

    @classmethod
    def record(
        cls,
        *,
        team_id: int,
        report_id: str,
        user_id: int,
        action_type: "SignalReportAction.ActionType",
        metadata: dict[str, Any] | None = None,
        bump_count: bool = True,
    ) -> None:
        """Upsert one interaction: bump the existing row or create it.

        Update-then-create rather than get_or_create so the common case (a repeat view) is one
        UPDATE; the create's unique-constraint race falls back to the update path.

        ``bump_count=False`` refreshes an existing row (metadata, ``last_at``) without counting
        it as a new interaction — for follow-up requests that amend one the row already counted,
        like the note trailing a thumbs rating. A create still starts at 1.
        """
        now = timezone.now()
        updates: dict[str, Any] = {"last_at": now}
        if bump_count:
            updates["count"] = models.F("count") + 1
        if metadata is not None:
            updates["metadata"] = metadata
        row = cls.objects.for_team(team_id).filter(report_id=report_id, user_id=user_id, type=action_type)
        if row.update(**updates):
            return
        try:
            with transaction.atomic():
                cls.objects.for_team(team_id).create(
                    team_id=team_id,
                    report_id=report_id,
                    user_id=user_id,
                    type=action_type,
                    metadata=metadata or {},
                    last_at=now,
                )
        except IntegrityError:
            row.update(**updates)


# ── Signals scout (headless cross-source explorer) ──────────────────────────────
#
# Core tables backing the Signals scout:
#   - SignalScoutConfig: per-team binding (one row per team).
#   - SignalScoutRun:    bridge from a `tasks.TaskRun` to its scout-domain context.
#                        Mirrors `SignalReportTask` (1:1 to TaskRun instead of N:1
#                        to Task because scout runs are per-execution, not per-task).
#                        Status, timing, error, chat-log all live on `TaskRun`;
#                        findings live on emitted `Signal`/`SignalReport` rows.
#   - SignalScratchpad:  working notes the scout reads in future runs.
#   - SignalScoutNote:   steering notes humans/agents leave for scouts to read.


class SignalScoutConfig(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """One row per (team, scout skill): schedule + emit posture for a `signals-scout-*` skill.

    Changes are activity-logged (they drive spend). Team-level participation in the
    dogfood program is gated by the `signals-scout` flag at the coordinator, not here.
    """

    # ModelActivityMixin only logs deletes when this is set.
    activity_logging_on_delete = True

    class Status(models.TextChoices):
        """Lifecycle states a writer deliberately moves a scout between.

        Deliberately small: only states that change what the scheduler does belong here.
        Windowed assessments (engagement, cold-start newness, a failing-but-not-tripped
        streak) are derived at read time, never persisted as a status.
        """

        ACTIVE = "active", "Active"
        # Warned by a system writer. Still scheduled; whether the warning later advances to a
        # pause depends on its reason (an `ignored` warning pauses after a grace period, a
        # `no_output` one only ever warns). A state rather than a notification so the sweep
        # that sets it is idempotent and any human touch has something concrete to clear.
        PENDING_PAUSE = "pending_pause", "Pending pause"
        PAUSED_BY_SYSTEM = "paused_by_system", "Paused by system"
        # A human switched the scout off. No system writer may resume or re-pause it.
        PAUSED_BY_USER = "paused_by_user", "Paused by user"

    class PauseReason(models.TextChoices):
        """Why a system writer paused (or warned) a scout.

        Each value also identifies the writer that owns the pause: a system writer may only
        clear or overwrite a pause carrying its own reason (`transition_status_by_system`),
        which is what keeps independent pause mechanisms from undoing each other.
        """

        NO_OUTPUT = "no_output", "No output"
        IGNORED = "ignored", "Ignored"
        REPEATED_FAILURES = "repeated_failures", "Repeated failures"

    class NetworkAccess(models.TextChoices):
        """What the scout's sandbox can reach over the network during a run.

        `trusted` maps to the Tasks sandbox `TRUSTED` level (the platform's default
        trusted-domain allowlist); `full` maps to `FULL` (unrestricted egress). Room is
        deliberately left for a `custom` choice carrying a user-supplied domain allowlist
        later — mirror the Tasks `SandboxEnvironment.NetworkAccessLevel` vocabulary when
        adding it so the mapping in the runner stays one-to-one.
        """

        TRUSTED = "trusted", "Trusted domains only"
        FULL = "full", "Full"

    # The `status` side of the `enabled` dual-write: a scout in one of these statuses is
    # scheduled by the coordinator. `pending_pause` still runs; the warning is not a pause.
    RUNNABLE_STATUSES = (Status.ACTIVE, Status.PENDING_PAUSE)

    # The pause reasons the inactivity sweep owns (`scout_harness/inactivity.py`): `no_output`
    # for a scout that surfaced nothing, `ignored` for one whose output nobody picked up. On the
    # model rather than the sweep because the update serializer also reads them: a human
    # re-enable of a pause carrying one of these emits the sweep's false-positive metric
    # (`signals_scout_auto_pause_reverted`).
    INACTIVITY_PAUSE_REASONS = (PauseReason.NO_OUTPUT, PauseReason.IGNORED)

    # How long a scout is treated as provisional after creation or a human re-enable, during
    # which system writers should leave it alone (`in_cold_start_grace`).
    COLD_START_GRACE = timedelta(days=14)

    # Bounds on `tags`. Tags are a grouping aid over a fleet an org can only grow so far, not a
    # taxonomy — the caps keep the column small and the fleet filter's option list scannable.
    MAX_TAGS = 10
    MAX_TAG_LENGTH = 50

    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin stays fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling for Django framework internals
    # (admin changelist queryset, related-object access, prefetch_related) that must not
    # filter by team. `default_manager_name` routes `_default_manager` / `_base_manager`
    # there. Same pattern as ProductTeamModel — duplicated here because TeamScopedRootMixin
    # doesn't bake it in (most callers don't need it).
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_scout_configs",
    )
    # The `signals-scout-*` LLMSkill this row references (controlling only its scheduling /
    # enablement, not the skill itself). The coordinator auto-creates a
    # row when it discovers a scout skill on a participating team, so a user authoring
    # `signals-scout-foo` gets a row (on the default schedule) on the next tick.
    skill_name = models.CharField(max_length=200)
    # Derived from `status` (`enabled = status in RUNNABLE_STATUSES`), but kept as a real
    # column because the coordinator filters on it at SQL level and the warehouse mirrors it.
    # `save` reconciles the pair for writers that only set one side; a DB constraint backstop
    # is deferred to a follow-up migration (see Meta.constraints) so rolling deploys with
    # enabled-only writers still in flight don't break.
    enabled = models.BooleanField(default=True, db_default=True)
    # Source of truth for the scout's lifecycle. Two of the four states pause scheduling; who
    # set the pause is the state itself (`paused_by_user` vs `paused_by_system`), not a
    # side-channel field, because the two must behave differently: the system may resume its
    # own pauses but must never touch a human's.
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_default=Status.ACTIVE,
    )
    # Set only alongside `pending_pause` / `paused_by_system`; see `PauseReason`.
    pause_reason = models.CharField(
        max_length=20,
        choices=PauseReason.choices,
        null=True,
        blank=True,
    )
    # When `status` last changed. Bookkeeping that rides along with the logged status change
    # itself, so it is excluded from activity logging. Null until the first transition;
    # `created_at` anchors the cold-start grace window for rows that never transitioned.
    status_changed_at = models.DateTimeField(null=True, blank=True)
    # Who last moved `status`, when a human did (through the config API). Null for system
    # transitions, unattributed writes, and rows whose status never changed. The enum already
    # says whether a pause is human or system; this adds WHO for human actions and tells a
    # human re-enable apart from a system resume. Who last edited anything else on the row
    # stays the activity log's job. `db_constraint=False` because posthog_user is a hot table
    # and adding the FK constraint would lock it; integrity is app-level only, like the
    # constraint-free path recommended for hot-table FKs. `db_index=False` because nothing
    # queries by attribution (it is read per-row) and the FK's default index would otherwise
    # be built non-concurrently inside the migration.
    status_changed_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    # Opt-out from the inactivity sweep (`scout_harness/inactivity.py`) — a watchdog whose whole
    # value is staying quiet (health checks, inbox validation) is *supposed* to surface nothing
    # most weeks, so silence must never read as waste. Only ever set explicitly: a re-enable of a
    # swept scout relies on the `in_cold_start_grace` re-anchor for its fresh window instead of
    # minting permanent immunity. `db_default` alongside `default` keeps the AddField
    # non-blocking and the column populated for writers that don't know about it yet.
    auto_pause_exempt = models.BooleanField(default=False, db_default=False)
    # Dry-run vs emit. Defaults emit-on so a freshly authored scout is live from its first
    # tick. Flip to False for dry-run — the scout runs and logs but `emit_finding` writes
    # nothing — to validate it on a team before its findings reach the inbox.
    emit = models.BooleanField(default=True, db_default=True)
    # Minutes between runs. Without a cron schedule, the coordinator dispatches this scout when
    # `last_run_at is None or now - last_run_at >= run_interval_minutes`. Deterministic —
    # no sampling. Floor of 30 keeps one scout from monopolizing the worker pool and matches the
    # tightest cadence the UI offers (RUN_INTERVAL_OPTIONS); default
    # 1440 = every 24 hours. Ceiling 43200 = 30 days. `PositiveIntegerField` (int4) not
    # `PositiveSmallIntegerField` (smallint, max 32767) so the documented 30-day ceiling fits.
    # Default chosen for run economics: most runs close out without a finding, so a tighter
    # cadence mostly pays to re-confirm "nothing new"; a daily cadence cuts per-scout spend
    # materially with negligible detection latency for non-spike findings. The flag's
    # `enabled_interval_minutes` can still override this per launch posture, and any scout is
    # tunable per row via the config API.
    run_interval_minutes = models.PositiveIntegerField(
        default=1440,
        db_default=1440,
        validators=[MinValueValidator(30), MaxValueValidator(43200)],
    )
    # What the scout's sandbox can reach over the network. The runner maps this to the Tasks
    # sandbox environment the run is provisioned into: `trusted` (default) keeps runs on the
    # platform's trusted-domain allowlist, `full` lifts the restriction for scouts whose skill
    # needs arbitrary external reads (docs, papers, status pages). Deliberately NOT excluded
    # from activity logging — flipping a scout to full network is a security-relevant change.
    # `db_default` alongside `default` keeps the AddField non-blocking and the column
    # populated for writers that don't know about it yet.
    network_access = models.CharField(
        max_length=20,
        choices=NetworkAccess.choices,
        default=NetworkAccess.TRUSTED,
        db_default=NetworkAccess.TRUSTED,
    )
    # Optional agent-model pin for this scout's runs, e.g. `claude-opus-4-5`. Null keeps the
    # normal resolution chain (the `scouts-model-selection` experiment gate, then the pipeline
    # runtime pin, then the agent-server default). Honored at dispatch only while the
    # `scouts-model-config` flag is on for the team, so a stored value is inert outside the
    # dogfood — the flag is the kill switch, which is why the value itself is not cleared when
    # the flag goes off. Free-form rather than a choices list: the model catalog changes
    # without deploys, and `model_selection` already treats an unroutable id defensively.
    model = models.CharField(max_length=200, null=True, blank=True)
    # Optional destinations for each finding or report this scout emits. Kept as a typed JSON object at
    # the API boundary so adding another destination does not require another pair of nullable
    # config columns. A Slack destination is active only when both its integration and channel
    # are present; the UI may persist the integration first while the user chooses a channel.
    output_destinations = models.JSONField(default=dict, db_default={})
    # Free-form labels for grouping the fleet ("revenue", "on-call", "experimental"). Normalized
    # to lowercase and deduped at the API boundary, so a tag means the same thing whoever typed
    # it. No GIN index: every read is already scoped to one team, and a team holds at most a
    # couple of dozen scouts, so `tags && ARRAY[...]` runs over a handful of rows.
    # `null=True` only so the AddField could land without a NOT NULL rewrite — the migration
    # backfilled existing rows with `{}` and every write path sends a list, so NULL carries no
    # meaning. Read through `tag_list` rather than this column so that stays an implementation
    # detail instead of leaking a nullable `tags` into the API and its generated clients.
    tags = ArrayField(
        models.CharField(max_length=MAX_TAG_LENGTH),
        default=list,
        null=True,
        blank=True,
    )
    # Optional JSON Schema (draft 2020-12, object-rooted) describing one structured record this
    # scout produces via `scout-record-output`. Null = the channel is off: the record endpoint
    # fails closed and the run prompt renders no structured-output section. Records land solely
    # as `$scout_structured_output` events in the project, so the channel also requires `emit`
    # (a dry-run scout has nowhere to record to). Serializer-validated (must compile as a
    # schema, bounded size) — this field is only written through the config API. The schema
    # describes ONE record; cardinality is the scout's call (one record per run, one per judged
    # entity, ...), so no separate mode enum is stored.
    structured_output_schema = models.JSONField(null=True, blank=True)
    # MCP gateway servers (UUIDs as strings) this scout's runs may mount, chosen from the
    # connections members shared to the whole team. Selection is per scout: the runner
    # snapshots it onto the task, and provisioning mounts only the team-scoped grants on the
    # listed servers, so an empty list mounts none. Personal grants never back a scout run,
    # which keeps runs identical no matter who created or edits the scout. Stale or unknown
    # ids simply never match a grant.
    # Deliberately NOT excluded from activity logging, because changing which external tools
    # a scout reaches is a security-relevant change, like `network_access`.
    mcp_gateway_server_ids = models.JSONField(default=list, db_default=[])
    # Optional five-field cron expression anchoring runs to wall-clock slots (e.g. "30 9 * * *",
    # "0 9,17 * * *", "0 9 * * 1-5"). Takes precedence over the rolling `run_interval_minutes`
    # when set. The coordinator evaluates it in `team.timezone`, so scheduled times follow
    # daylight-saving changes without storing a second timezone on every scout config.
    # Serializer-validated (croniter + a 30-minute minimum gap between occurrences, matching
    # the interval floor) — this field is only written through the config API.
    run_cron_schedule = models.CharField(max_length=100, null=True, blank=True)
    # Stamped by the config serializers only when a schedule field (`run_interval_minutes`,
    # `run_cron_schedule`) actually changes. The coordinator anchors the cron due-check on this
    # (not `updated_at`, which every save bumps) so an unrelated emit/enabled toggle can never
    # defer an already-overdue scheduled run. Null on rows whose schedule was never edited —
    # `created_at` anchors those.
    schedule_changed_at = models.DateTimeField(null=True, blank=True)
    # Stamped by the coordinator after each dispatch; drives the due-check. Written every
    # run, so it is excluded from activity logging (see field_exclusions below).
    last_run_at = models.DateTimeField(null=True, blank=True)
    # Failure-streak circuit breaker over this lane's run outcomes, maintained by the runner:
    # bumped on a failed run, zeroed on a successful one. At the threshold
    # `failure_streak_pause_threshold` derives from this lane's own schedule, the runner pauses it
    # (`transition_status_by_system`, `repeated_failures`) and the
    # coordinator holds it to one probe per `AUTO_PAUSE_PROBE_INTERVAL_S`. Without it a lane
    # that can never succeed re-dispatches forever, taking a full-length sandbox lease per
    # interval to produce nothing. Written on every run, so it is excluded from activity
    # logging like `last_run_at`; the pause itself logs through `status` like any other.
    consecutive_failure_count = models.PositiveIntegerField(default=0, db_default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Who last flipped `enabled` on. Tracked because enablement drives spend.
    enabled_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Which product created this scout and which of its objects the scout belongs to. Signals owns
    # scouts, but another product can stand one up for one of its own objects (Replay Vision creates
    # one per scanner), and that product needs to find its scouts again, authorize reads against the
    # owning object, and clean up when the object goes. Same `(source_product, source_id)` shape the
    # rest of Signals uses for cross-product provenance. Null for a scout a person created directly.
    source_product = models.CharField(max_length=100, choices=signal_source_product_choices, null=True, blank=True)
    source_id = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        verbose_name = "Signal scout config"
        verbose_name_plural = "Signal scout configs"
        default_manager_name = "all_teams"
        indexes = [
            # The owning product's lookup: "which scouts belong to this object of mine".
            models.Index(fields=["team", "source_product", "source_id"], name="scout_config_source_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "skill_name"], name="unique_scout_config_per_team_skill"),
            # Backstop for the dual-write in `save`: added NOT VALID + validated (0080–0082)
            # only after the 0077 deploy fully rolled, because enforcing it in the same deploy
            # that introduced the dual-write would break not-yet-replaced instances that still
            # write `enabled` alone.
            models.CheckConstraint(
                name="scout_config_enabled_matches_status",
                condition=models.Q(enabled=True, status__in=["active", "pending_pause"])
                | models.Q(enabled=False, status__in=["paused_by_system", "paused_by_user"]),
            ),
            models.CheckConstraint(
                name="scout_config_pause_reason_matches_status",
                condition=models.Q(status__in=["pending_pause", "paused_by_system"], pause_reason__isnull=False)
                | models.Q(status__in=["active", "paused_by_user"], pause_reason__isnull=True),
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Keep the `enabled` / `status` pair consistent for writers that only set one side.

        `status` is the source of truth, but callers that predate it (fixtures, ad-hoc
        scripts, the config API's `enabled` field) still write `enabled` alone. When the pair
        disagrees at save time, resolve toward whichever side the caller touched: `status`
        wins when `update_fields` names it without `enabled`, or on a create where a
        non-default status was passed explicitly; otherwise the `enabled` value is taken as
        the intent (True resumes any pause, False records a user pause).
        """
        update_fields = kwargs.get("update_fields")
        if self.enabled != (self.status in self.RUNNABLE_STATUSES):
            fields = set(update_fields) if update_fields is not None else None
            status_is_intent = (
                ("status" in fields and "enabled" not in fields)
                if fields is not None
                else (self._state.adding and self.status != self.Status.ACTIVE)
            )
            if status_is_intent:
                self.enabled = self.status in self.RUNNABLE_STATUSES
                touched = {"enabled"}
            else:
                self.status = self.Status.ACTIVE if self.enabled else self.Status.PAUSED_BY_USER
                self.pause_reason = None
                # An enabled-only write carries no actor, so the attribution stamp is cleared
                # rather than left pointing at whoever made the previous transition.
                self.status_changed_by = None
                touched = {"status", "pause_reason", "status_changed_by"}
                if not self._state.adding:
                    self.status_changed_at = timezone.now()
                    touched.add("status_changed_at")
            if fields is not None:
                kwargs["update_fields"] = fields | touched
        super().save(*args, **kwargs)

    @classmethod
    def _pause_reasons_share_writer(cls, current: str | None, incoming: "SignalScoutConfig.PauseReason") -> bool:
        """The ownership rule compares writers, not exact reasons: the inactivity sweep owns
        both `no_output` and `ignored`, and must be able to reclassify its own warning from
        one to the other without being refused as a foreign writer."""
        if current == incoming:
            return True
        inactivity: set[str] = set(cls.INACTIVITY_PAUSE_REASONS)
        return current in inactivity and incoming in inactivity

    def transition_status_by_system(
        self,
        new_status: "SignalScoutConfig.Status",
        *,
        pause_reason: "SignalScoutConfig.PauseReason",
        evaluated_at: datetime | None = None,
    ) -> bool:
        """Apply a system-driven status transition under the reason-scoped ownership rule.

        `pause_reason` names the calling writer (an inactivity sweep passes `no_output` or
        `ignored`, a failure breaker `repeated_failures`) as well as the reason recorded on a
        pause. The rule: a system writer may never touch `paused_by_user`, and may only move a
        scout whose current pause carries a reason it owns (`_pause_reasons_share_writer`), so
        independent pause mechanisms cannot clear or overwrite each other's state. The checks run against a freshly locked row,
        not the caller's instance, so a human pause or another writer's claim that landed
        after the caller read the row cannot be overwritten. Pass `evaluated_at` (when the
        caller read the state its decision is based on) to also refuse the transition if the
        status moved after that moment, e.g. a human re-enable racing a sweep's pause.
        Saves and returns True when the transition applies; returns False without writing
        when it is refused or a no-op.
        """
        if new_status == self.Status.PAUSED_BY_USER:
            raise ValueError("Only a user write may set paused_by_user.")
        with transaction.atomic():
            # One ordered query locks the whole team's rows, not just ours: the cap check below
            # counts sibling rows, so two concurrent resumes locking only their own rows would
            # each read the other as still paused and both slip under the cap. A single ordered
            # lock set also keeps concurrent transitions on one team deadlock-free. Team config
            # counts are small (capped) and transitions rare, so the wider lock is cheap.
            team_rows = {
                row.pk: row
                for row in type(self).all_teams.select_for_update().filter(team_id=self.team_id).order_by("pk")
            }
            locked = team_rows.get(self.pk)
            if locked is None:
                return False
            if locked.status == self.Status.PAUSED_BY_USER:
                return False
            if locked.status != self.Status.ACTIVE and not self._pause_reasons_share_writer(
                locked.pause_reason, pause_reason
            ):
                return False
            # A warning is weaker than a pause: a delayed or retried warn must not reopen a
            # scout its own writer already paused (pending_pause is runnable).
            if new_status == self.Status.PENDING_PAUSE and locked.status == self.Status.PAUSED_BY_SYSTEM:
                return False
            if (
                evaluated_at is not None
                and locked.status_changed_at is not None
                and locked.status_changed_at > evaluated_at
            ):
                return False
            # A resume must not carry the team past the enabled-scout cap: the pause freed a
            # slot the config API may have legitimately given to another scout since.
            from products.signals.backend.scout_harness.limits import (  # noqa: PLC0415 — importing via the scout_harness package init would put lazy_seed/skill_loader on the django.setup() path that loads this module
                MAX_ENABLED_SCOUTS_PER_TEAM,
            )

            if new_status in self.RUNNABLE_STATUSES and locked.status not in self.RUNNABLE_STATUSES:
                peers = sum(1 for row in team_rows.values() if row.enabled and row.pk != locked.pk)
                if peers >= MAX_ENABLED_SCOUTS_PER_TEAM:
                    return False
            recorded_reason = None if new_status == self.Status.ACTIVE else pause_reason
            if new_status == locked.status and recorded_reason == locked.pause_reason:
                return False
            locked.status = new_status
            locked.pause_reason = recorded_reason
            locked.status_changed_at = timezone.now()
            locked.status_changed_by = None
            locked.enabled = new_status in self.RUNNABLE_STATUSES
            update_fields = [
                "status",
                "pause_reason",
                "status_changed_at",
                "status_changed_by",
                "enabled",
                "updated_at",
            ]
            if new_status == self.Status.ACTIVE:
                # A resume always starts with a clean failure streak — otherwise the very next
                # failed run would re-trip the breaker off stale evidence.
                locked.consecutive_failure_count = 0
                update_fields.append("consecutive_failure_count")
            locked.save(update_fields=update_fields)
        for field in (
            "status",
            "pause_reason",
            "status_changed_at",
            "status_changed_by",
            "enabled",
            "consecutive_failure_count",
        ):
            setattr(self, field, getattr(locked, field))
        return True

    def in_cold_start_grace(self) -> bool:
        """True while the scout is provisional and system writers should not evaluate it.

        Anchored on `created_at`, re-anchored by any move back to `active`: a re-enable or a
        system resume grants a fresh window before the next evaluation. Deliberately not
        keyed on `status_changed_by` so the window survives the actor's account being
        deleted (`SET_NULL`). A `pending_pause` warning never re-anchors (status is not
        `active`), so a sweep cannot put its own candidates back into grace. Time-based
        only; a consumer that also wants a minimum-runs floor applies that on top, since the
        floor differs per writer.
        """
        anchor = self.created_at
        if self.status == self.Status.ACTIVE and self.status_changed_at is not None:
            anchor = max(anchor, self.status_changed_at)
        return timezone.now() < anchor + self.COLD_START_GRACE

    @property
    def tag_list(self) -> list[str]:
        """`tags` with the nullable column's NULL folded away, for readers.

        The API serializes this rather than the column so `tags` is a plain non-null list
        everywhere downstream. Serializing the column directly would surface `null` in the
        OpenAPI schema and, through the generated clients, force every consumer to tell "no
        tags" apart from "not set" — a distinction the column does not actually carry, since
        the AddField backfilled existing rows and every write path sends a list.
        """
        return self.tags or []

    def _get_before_update(self, **kwargs: Any) -> "SignalScoutConfig | None":
        # ModelActivityMixin's prior-state lookup goes through `objects` (the fail-closed
        # TeamScopedManager). Edits from Django admin / the coordinator / a shell run with no
        # team scope set, so route the lookup through the unscoped `all_teams` manager to avoid
        # a TeamScopeError when logging the change.
        if not self.pk:
            return None
        return type(self).all_teams.filter(pk=self.pk).first()


class SignalScoutRun(TeamScopedRootMixin, UUIDModel):
    """Bridge from a Tasks `TaskRun` to the scout skill that ran inside it.

    Mirrors `SignalReportTask` (the bridge used by the SignalReport research flow):
    a thin row that links a `tasks.TaskRun` to its scout-domain context. Status,
    timing, error, and chat-log live on the `TaskRun`; emitted findings are
    `Signal` / `SignalReport` rows created by `emit_signal`. This row carries only
    the scout-specific fields that need to be queryable as real columns
    (`skill_name` for the per-team running-check, `scout_config` for audit lineage,
    and the `emitted_count` / `emitted_finding_ids` emit tally so "did this run
    surface anything?" is a column lookup, not a prose-`summary` parse).
    """

    # See SignalScoutConfig.all_teams for rationale.
    all_teams = models.Manager()  # noqa: DJ012

    # 1:1 with the TaskRun the scout span ran inside. CASCADE: if the TaskRun is
    # purged (data retention), the scout-side bridge row goes with it.
    task_run = models.OneToOneField(
        "tasks.TaskRun",
        on_delete=models.CASCADE,
        related_name="signal_scout_run",
    )
    # Denormalised tenant boundary. Canonical via `task_run.task.team`, but kept
    # on this row so per-team queries (e.g. running-check) avoid the join and the
    # `TeamScopedRootMixin` fail-closed manager has a column to filter on.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_scout_runs",
    )
    # SET_NULL so deleting a config row (e.g. recreating from scratch) doesn't
    # destroy the run history we want for audit and dedupe.
    scout_config = models.ForeignKey(
        SignalScoutConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="runs",
    )
    skill_name = models.CharField(max_length=200)
    skill_version = models.IntegerField()
    # One-paragraph close-out the scout writes at end-of-run via `SignalScoutRunSummary`.
    # Searchable via ILIKE on the list endpoint — the dedupe path for runs that didn't
    # emit any findings (and so left no `Signal` row to query against). Empty default
    # so historical rows and mid-run reads return a string, not NULL.
    summary = models.TextField(blank=True, default="", db_default="")
    # Tally of findings this run actually emitted (preflight-skipped/dry-run emits don't
    # count). Bumped post-success by `emit_finding`; kept as a real column so a run that
    # surfaced something is queryable directly (the `emitted` filter on the list endpoint)
    # instead of parsing the prose `summary`. NOT an idempotency barrier — re-emitting the
    # same `finding_id` increments it again, just like it emits a second signal.
    # Nullable (with a 0 `db_default`) so the AddField stays non-blocking on a table that
    # already has rows — new and historical rows both read 0; NULL is permitted but never
    # written by the ORM path.
    emitted_count = models.IntegerField(null=True, default=0, db_default=0)
    # The `finding_id`s behind `emitted_count`, in emit order — lets a caller tie a run back
    # to its `Signal` rows (`source_id = run:<run_id>:finding:<finding_id>`) without a
    # ClickHouse scan. Parallel to `emitted_count` (`len(emitted_finding_ids) == emitted_count`).
    emitted_finding_ids = models.JSONField(null=True, blank=True, default=list, db_default=[])
    # The `SignalReport` ids a run authored directly via `emit_report` (the second emit channel),
    # in emit order. Parallel to `emitted_finding_ids` but for the report-authoring path: a scout
    # that opts into `emit_report` writes a full report rather than a weak signal, so its output
    # isn't a `finding_id` -> signal but a `report_id` the run owns. Lets "which reports did this
    # run create/edit?" be a column lookup. Nullable with a `[]` db_default so the AddField stays
    # non-blocking on the populated table — new and historical rows both read `[]`.
    emitted_report_ids = models.JSONField(null=True, blank=True, default=list, db_default=[])
    # The `SignalReport` ids a run *mutated* via `edit_report` (rewrote title/summary and/or appended a
    # note) — the edit-channel counterpart to `emitted_report_ids`. Deduped (set-membership, not a
    # multiset): a run that edits the same report twice records it once, because the queryable question
    # is "which reports did this run touch?", not "how many edits did it make" — that detail lives in the
    # per-report artefact log. Distinct from `emitted_report_ids` because `edit_report` targets ANY inbox
    # report (pipeline-authored included), so an edited id is generally NOT one the run authored. Nullable
    # with a `[]` db_default so the AddField stays non-blocking on the populated table.
    edited_report_ids = models.JSONField(null=True, blank=True, default=list, db_default=[])
    # Scout-owned per-run context — the native home for run dimensions that matter operationally
    # but don't each warrant a dedicated column. Two regions, distinguished by who writes them.
    # Top-level keys are stamped write-once by the runner at run creation, and split by whether
    # they are always present. `harness_prompt_version` / `report_channel` / `skill_origin` always
    # are: they pin down which instructions the run was given, and each is unrecoverable later
    # (the prompt has no version history, `allowed_tools` can be edited, and a seeded row flips to
    # `custom` the moment a team edits it), which is what makes them worth stamping rather than
    # resolving at read time. `model` / `runtime_adapter` / `reasoning_effort` appear only when the
    # `scouts-model-selection` gate or a runtime pin overrode the agent-server default, so their
    # absence is meaningful. New runner-known dimensions belong there, stamped by `_create_run_row`.
    # The nested `derived` object is written once at finalize by
    # `scout_harness/derived_metadata.py` and holds booleans the harness computes from the run's
    # own output, so "what kind of run was this?" is a field lookup rather than prose parsing.
    # Both regions are server-written: nothing here is scout-authored, which is what makes the
    # column safe to query directly.
    # Nullable with a `{}` db_default so the AddField stays non-blocking on the populated table.
    metadata = models.JSONField(null=True, blank=True, default=dict, db_default={})
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal scout run"
        verbose_name_plural = "Signal scout runs"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["team", "skill_name"], name="signal_scout_run_skill_idx"),
            # The per-scout run window ("last N runs of each scout") probes one scout at a time,
            # constraining all three keys, so each probe reads only the entries it returns. The
            # index above stops at the partition key, which leaves the planner sorting every one of
            # a scout's runs to take the newest N — on a table that only ever grows, and a read the
            # inbox repeats every 60 seconds.
            models.Index(
                fields=["team", "skill_name", "-created_at"],
                name="signal_scout_run_recent_idx",
            ),
            # "which run authored this report?" is a jsonb containment lookup (`@>`) that
            # `dismissal_notes` runs on the dismissal request path, batched into one OR'd query per
            # request. Without these the planner can only seq-scan the team's runs, and this table
            # grows about one row per scout per run interval with no pruning, so the scan would get
            # slower for the life of the project.
            GinIndex(fields=["emitted_report_ids"], name="signal_scout_run_emitted_idx"),
            GinIndex(fields=["edited_report_ids"], name="signal_scout_run_edited_idx"),
        ]


class SignalScoutEmission(TeamScopedRootMixin, UUIDModel):
    """One persisted row per finding a scout run emitted to the inbox.

    The durable, queryable record of *what* a scout surfaced — written at emit time by
    `emit_finding`, in the same transaction as the run's `emitted_count` tally bump. It lets a
    team (and its MCP agents) read a run's findings directly via API/MCP without scanning the
    ClickHouse signal store or parsing `source_id`. It complements, not replaces, that store:
    ClickHouse is keyed for embedding/grouping, lags emit by the fire-and-forget Temporal
    pipeline, and can drop under buffer backpressure — this row reflects the emit
    deterministically at the moment it fired.

    Parallel to `SignalScoutRun.emitted_finding_ids` (one row per emit, in emit order) and, like
    that tally, NOT an idempotency barrier: re-emitting the same `finding_id` writes a second
    row, mirroring the second signal it produces downstream.
    """

    # See SignalScoutConfig.all_teams for rationale: emit can run with no team scope set
    # (Temporal activity), so the write path needs the unscoped manager.
    all_teams = models.Manager()  # noqa: DJ012

    # Denormalised tenant boundary, matching `SignalScoutRun`. Canonical via `scout_run.team`,
    # kept on this row so the `TeamScopedRootMixin` fail-closed manager has a column to filter on.
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_scout_emissions",
    )
    # CASCADE: an emission is meaningless without its run; purging the run (or the TaskRun it
    # bridges, via that row's own CASCADE) takes the per-finding rows with it.
    scout_run = models.ForeignKey(
        SignalScoutRun,
        on_delete=models.CASCADE,
        related_name="emissions",
    )
    # Stable finding id the agent emitted under — baked into `source_id` below and present in the
    # run's `emitted_finding_ids`.
    finding_id = models.CharField(max_length=200)
    # The emitted signal's `description` (the finding prose surfaced to the inbox). Bounded
    # upstream by `MAX_FINDING_DESCRIPTION_LENGTH` on the emit serializer and the emit_signal
    # token cap, so it stays well clear of row-size concerns.
    description = models.TextField()
    weight = models.FloatField()
    confidence = models.FloatField()
    severity = models.CharField(max_length=20, null=True, blank=True)
    # Slug tags the scout attached to the finding (normalized lowercase kebab-case, capped at
    # emit). This row is what feeds the per-scout tag-vocabulary feedback loop in the run prompt
    # (`recent_tag_usage`), so the vocabulary derives from emitted behavior, not a maintained list.
    tags = models.JSONField(default=list, blank=True)
    # Deterministic `run:<run_id>:finding:<finding_id>` — the join key back into the signal store
    # for the full embedding/grouping view of this finding.
    source_id = models.CharField(max_length=200)
    emitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal scout emission"
        verbose_name_plural = "Signal scout emissions"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["team", "scout_run"], name="signal_scout_emission_run_idx"),
        ]


class SignalScratchpad(TeamScopedRootMixin, UUIDModel):
    """Narrow per-team memory surface for the Signals scout fleet — MCP-readable across agents.

    Scratchpad entries are keyed prose notes the scout fleet writes during runs and
    reads back on future runs (intra-fleet memory) — classifications, dedupe
    fingerprints, learned team quirks the scout decided not to re-emit. The MCP
    read surface is intentional product design: any agent (PostHog AI, ad-hoc
    investigators, other scouts) can read what the scout fleet has learned about
    a team.

    Distinct in shape from PostHog AI's memory primitives (`CoreMemory`,
    `AgentMemory`) — those are singleton-per-team blob or per-conversation
    embedded snippets, neither of which fits the scout's per-key cross-agent
    read pattern. Kept narrow to the scouts feature on purpose; not a shared
    primitive.

    Most entries are durable, so `expires_at` is nullable and unset by default. It
    exists for the memories that are true only for a while — a cooldown, a window to
    watch — which a scout would otherwise have to come back and `forget` by hand.
    Expiry hides a row from `search_scratchpad`, it does not delete it: the key stays
    taken (so the upsert keeps working) and a human auditing the fleet's memory can
    still read it back with `include_expired`.
    """

    # See SignalScoutConfig.all_teams for rationale.
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_scratchpads",
    )
    # Semantic key, scout-chosen. Unique per team.
    key = models.CharField(max_length=300)
    # Prose for prompt injection — the scout reads this verbatim.
    content = models.TextField()
    # The run that wrote this entry. SET_NULL so deleting a run row doesn't
    # destroy the memory it left behind.
    created_by_run = models.ForeignKey(
        SignalScoutRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scratchpads_created",
    )
    # Null = durable (the default). Set to drop the entry out of scout searches once
    # its shelf life is up. Mirrors `SignalScoutNote.expires_at`.
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal scratchpad"
        verbose_name_plural = "Signal scratchpads"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name="signal_scratchpad_unique_team_key"),
        ]


class SignalScoutNote(TeamScopedRootMixin, UUIDModel):
    """Steering notes humans (or other agents) leave for the scout fleet — read at run time.

    The inbound complement to `SignalScratchpad`: scratchpad is what the fleet *learned*
    (agent-authored, sandbox-write-only); a note is what the team wants the fleet to *know*
    (authored via the user-grantable `signal_scout:write` scope). Notes are the lightweight
    steering channel for feedback and pointers that don't warrant editing a scout's skill
    body — "look into X", "stop flagging Y", "we shipped Z on Tuesday". A note targets one
    scout (`skill_name`) or the whole fleet (blank `skill_name`); each run lists the notes
    addressed to it as prior context and weighs them like any other input.

    Trust model: scouts read note content verbatim while holding privileged sandbox tools,
    so writing a note is gated to skill-authoring-level authorization — API keys need
    `llm_skill:write` on top of `signal_scout:write`, and every writer must clear the
    `llm_skill` RBAC editor bar (see `SignalScoutNoteViewSet`). A caller who can leave a
    note could therefore already steer the fleet by editing its skills; notes add a cheaper
    channel, not new power. The run prompt additionally frames note content as advisory
    steering that never overrides the harness ground rules.

    Two more writers derive rows from inbox activity, both re-checking the RBAC leg of this gate
    themselves (the actions behind them need only `task:write`) against the canonical project whose
    scouts read the row. They differ on the key-scope leg, because they differ on whether this note is
    the only way the text reaches a scout:
    - `REPORT_DISMISSAL` — judging a report with a note (dismiss, snooze, or restore; not resolve),
      see `dismissal_notes.py`. Its text also lands on the `dismissal_note` field of the reports API,
      which every scout is told to read, so the note opens no channel a `task:write` caller lacks and
      the key scopes aren't required on top.
    - `REPORT_DISCUSSION` — opening a discussion on a report with a question, see
      `discussion_notes.py`. The question otherwise lives only on the ephemeral discussion task, which
      is in no scout's run context, so this note is its sole carrier and the full gate applies —
      `llm_skill:write` and `signal_scout:write` included.
    - `REPORT_FEEDBACK` — rating a report useful/not useful with a note, see `feedback_notes.py`. Like
      a discussion the note is the only path the text takes to a scout (the rating otherwise lands only
      on a product-analytics event), so the full gate applies too. Forwarded only for a report with a
      resolvable authoring scout, since the feedback is a verdict on that scout's own report.
    `origin` keeps the kinds apart so the run prompt can frame a dismissal as one reviewer's verdict
    on one report, a discussion as a question to weigh, and feedback as a reader's rating — rather than
    fleet-level steering.
    """

    class Origin(models.TextChoices):
        HUMAN = "human", "Left directly"
        REPORT_DISMISSAL = "report_dismissal", "Derived from inbox dismissal feedback"
        REPORT_DISCUSSION = "report_discussion", "Derived from inbox discussion feedback"
        REPORT_FEEDBACK = "report_feedback", "Derived from inbox report feedback"

    # See SignalScoutConfig.all_teams for rationale.
    all_teams = models.Manager()  # noqa: DJ012

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating
    # this table takes no lock on those parents (app-level enforcement only).
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="signal_scout_notes",
    )
    # Target scout's skill name (`signals-scout-*`). Blank = a general note addressed to the
    # whole fleet — every scout's run sees it alongside its own skill-scoped notes.
    skill_name = models.CharField(max_length=200, blank=True, default="", db_default="")
    # Prose the scout reads verbatim. Bounded by the create serializer, not the column.
    content = models.TextField()
    # Who left the note. SET_NULL so removing a user keeps the note (its content still steers).
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    # Optional TTL — expired notes drop out of the default list view, so time-boxed steering
    # ("watch checkout closely this week") retires itself without a delete.
    expires_at = models.DateTimeField(null=True, blank=True)
    # How the row got here, surfaced to the run so a scout can weigh a reviewer's verdict on one
    # report differently from a skill author's fleet steering (see the trust model above). Carries
    # a `db_default` because the nodejs/rust test schema is built straight from model definitions
    # with migrations disabled, where a Python-only `default` is invisible.
    origin = models.CharField(max_length=32, choices=Origin, default=Origin.HUMAN, db_default=Origin.HUMAN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal scout note"
        verbose_name_plural = "Signal scout notes"
        default_manager_name = "all_teams"
        indexes = [
            # The run-time read is "recent notes for this team (optionally one skill)" — newest first.
            models.Index(fields=["team", "-created_at"], name="signal_scout_note_recent_idx"),
        ]


class SignalProjectProfile(TeamScopedRootMixin, UUIDModel):
    """Deterministic snapshot of "what's true about this project" — agent orientation surface.

    One row per (team, computed_at). Time-series so Phase 7 can diff a new profile against
    the previous row to populate `payload.deltas`. v1 (Phase 4a) writes inventory only;
    Phase 7 layers on deltas, activity_notes, and an LLM narrative section.

    Profile is the *deterministic ground truth* about a project (computed from authoritative
    tables). Distinct from `SignalScratchpad`, which is the *agent's inferred learnings* (possibly
    wrong, TTL'd). Profile feeds memory; memory does not update profile.
    """

    # See `SignalScoutConfig.all_teams` for the rationale on the unscoped sibling manager
    # and `default_manager_name`.
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_project_profiles",
    )
    computed_at = models.DateTimeField(auto_now_add=True)
    # Soft TTL — `get_project_profile` treats rows past expiry as cache misses and recomputes.
    # Aligned to the coordinator tick (`PROFILE_TTL`) so an active team's agent runs see
    # ground-truth that's at most one tick stale. Callers that know the underlying data
    # just changed can punch through the cache via `get_project_profile(force_refresh=True)`.
    expires_at = models.DateTimeField()
    # Bumps when the inventory schema changes meaningfully so `get_project_profile` can
    # invalidate stale rows without a manual backfill.
    source_version = models.CharField(max_length=40)
    # Structured payload: `{inventory: {...}}` in v1; `deltas`, `activity_notes`, `narrative`
    # slots reserved for Phase 7. Stored as jsonb because the payload is written by one
    # builder, read whole, and never field-queried — relational columns would buy no query
    # benefit and a migration per section as coverage grows. Not schemaless, though:
    # `build_inventory` returns a validated `Inventory` model (see
    # `scout_harness/profile/schema.py`), so the jsonb is schema-backed on write.
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Signal project profile"
        verbose_name_plural = "Signal project profiles"
        default_manager_name = "all_teams"
        indexes = [
            # `get_project_profile` reads the newest non-expired row for a team — supports the
            # ORDER BY computed_at DESC LIMIT 1 lookup pattern.
            models.Index(fields=["team", "-computed_at"], name="signal_proj_profile_recent_idx"),
        ]


class SignalRepositoryAreaActivity(TeamScopedRootMixin, UUIDModel):
    """Cached recent-contributor map for one (repository, area) pair.

    Backs recency-aware reviewer suggestion (`report_generation/repo_activity.py`). An
    *area* is a path prefix (see `area_for_path`); `""` means the repository root. Rows are
    created on demand, refreshed lazily when stale, and kept warm by the weekly
    `refresh_signal_repository_activity` task — which only re-fetches rows read recently
    (`last_used_at`), so abandoned areas age out of the warm set.
    """

    # db_constraint=False: creating an FK constraint locks the hot posthog_team table and
    # has blocked deploys — app-level enforcement only (same as SignalReportRefund).
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_repo_area_activities",
        db_constraint=False,
    )
    # Normalized "owner/repo", lowercase.
    repository = models.CharField(max_length=400)
    area = models.CharField(max_length=400, blank=True)
    # [{login, name, commit_count, last_commit_at, last_commit_sha, last_commit_url}]
    contributors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Null until the first successful GitHub fetch.
    refreshed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Signal repository area activity"
        verbose_name_plural = "Signal repository area activities"
        constraints = [
            models.UniqueConstraint(fields=["team", "repository", "area"], name="signal_repo_area_activity_uniq"),
        ]
