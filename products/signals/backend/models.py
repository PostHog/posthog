import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, cast

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

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
    Dismissal,
    LogArtefactContent,
    SignalFinding,
    StatusArtefactContent,
    TaskRunArtefact,
    artefact_type_for,
    parse_artefact_content,
    task_run_identifier_for_legacy_relationship,
)

logger = logging.getLogger(__name__)


class SignalSourceConfig(UUIDModel):
    class SourceProduct(models.TextChoices):
        SESSION_REPLAY = "session_replay", "Session replay"
        LLM_ANALYTICS = "llm_analytics", "LLM analytics"
        GITHUB = "github", "GitHub"
        LINEAR = "linear", "Linear"
        ZENDESK = "zendesk", "Zendesk"
        CONVERSATIONS = "conversations", "Conversations"
        ERROR_TRACKING = "error_tracking", "Error tracking"
        PGANALYZE = "pganalyze", "pganalyze"
        SIGNALS_SCOUT = "signals_scout", "Signals scout"
        LOGS = "logs", "Logs"
        HEALTH_CHECKS = "health_checks", "Health checks"
        ENDPOINTS = "endpoints", "Endpoints"
        REPLAY_VISION = "replay_vision", "Replay Vision"

    class SourceType(models.TextChoices):
        SESSION_ANALYSIS_CLUSTER = "session_analysis_cluster", "Session analysis cluster"
        EVALUATION = "evaluation", "Evaluation"
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

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="signal_source_configs")
    source_product = models.CharField(max_length=100, choices=SourceProduct)
    source_type = models.CharField(max_length=100, choices=SourceType)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    @classmethod
    def is_source_enabled(cls, team_id: int, source_product: str, source_type: str) -> bool:
        """Check whether a given signal source is enabled for a team.

        Scout findings are on by default (see below). For everything else, the team must have a
        SignalSourceConfig row with enabled=True. AI observability evaluation signals additionally
        carry a per-evaluation allowlist in the config row, enforced upstream in the llma evals
        workflows — the row check here is the team-level gate.
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


class SignalTeamConfig(UUIDModel):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="signal_team_config",
    )
    default_autostart_priority = models.CharField(max_length=2, choices=AutonomyPriority, default=AutonomyPriority.P4)
    default_slack_notification_channel = models.CharField(max_length=255, null=True, blank=True)
    autostart_base_branches = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal team config"
        verbose_name_plural = "Signal team configs"


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

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status, default=Status.POTENTIAL)
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

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
            # - READY | RESOLVED -> CANDIDATE when new matching signals reopen the report for
            #   summary / agentic research (READY: every signal; resolved: recurrence of the issue)
            case (S.POTENTIAL | S.READY | S.RESOLVED, S.CANDIDATE):
                self.promoted_at = timezone.now()
                updated_fields.add("promoted_at")

            case (S.CANDIDATE, S.IN_PROGRESS):
                if signals_at_run_increment is None:
                    raise ValueError("signals_at_run_increment is required for candidate -> in_progress")
                self.last_run_at = timezone.now()
                self.signals_at_run = self.signal_count + signals_at_run_increment
                self.run_count += 1
                updated_fields.update(["last_run_at", "signals_at_run", "run_count"])

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

            # Reset to potential (from in_progress via actionability judge, from suppressed, or by user snooze on a ready report)
            case (S.IN_PROGRESS | S.SUPPRESSED | S.READY | S.RESOLVED, S.POTENTIAL):
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
        if title is not None:
            self.title = title
            updated_fields.add("title")
        if summary is not None:
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


class SignalReportArtefact(UUIDModel):
    class ArtefactType(models.TextChoices):
        VIDEO_SEGMENT = "video_segment"
        SAFETY_JUDGMENT = "safety_judgment"
        ACTIONABILITY_JUDGMENT = "actionability_judgment"
        PRIORITY_JUDGMENT = "priority_judgment"
        SIGNAL_FINDING = "signal_finding"
        REPO_SELECTION = "repo_selection"
        SUGGESTED_REVIEWERS = "suggested_reviewers"
        DISMISSAL = "dismissal"
        CODE_REFERENCE = "code_reference"
        COMMIT = "commit"
        TASK_RUN = "task_run"
        NOTE = "note"
        TITLE_CHANGE = "title_change"
        SUMMARY_CHANGE = "summary_change"
        CODE_REVIEW = "code_review"

    # Every artefact is an append-only, point-in-time log entry — nothing is mutated in place by
    # the producers. The two sets below classify *what an entry means*, not how it is written:
    #   - status artefacts describe the report's current state (judgments, repo selection,
    #     suggested reviewers). They are appended on each (re)assessment via `append_status`; the
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
        }
    )

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100, choices=ArtefactType)
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

    class Meta:
        indexes = [
            models.Index(fields=["report"], name="signals_sig_report__idx"),
            # For JOINs involving matching a report to artifact of a certain type
            models.Index(fields=["report", "type"], name="signals_sig_report_type_idx"),
            # Latest-wins lookups: artefacts are append-only, so deriving the current status / log
            # tail is `WHERE report=? AND type=? ORDER BY created_at DESC` — this makes it a seek.
            models.Index(fields=["report", "type", "-created_at"], name="signals_sig_rpt_type_ct_idx"),
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
        """
        if artefact_type_for(content) not in cls.LOG_ARTEFACT_TYPES:
            raise ValueError(f"{type(content).__name__} is not a log artefact content model")
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

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
        return cls._create(team_id=team_id, report_id=report_id, content=content, attribution=attribution)

    def update_content(self, content: str | dict | list) -> None:
        """Replace this artefact's content in place (bumps `updated_at`), parsed and validated
        against the row's type. Attribution is creation-time only — edits don't reassign it.

        Editing the latest `suggested_reviewers` row changes the report's canonical reviewers,
        so it re-evaluates auto-start the same way appending a new reviewers row does."""
        parsed = parse_artefact_content(self.type, content)
        # The `task` FK is the association and is creation-time only; an edit must not let
        # content.task_id drift away from it.
        if isinstance(parsed, TaskRunArtefact) and str(parsed.task_id) != str(self.task_id):
            raise ArtefactContentValidationError(
                "task_run content.task_id must match the artefact's task and cannot be reassigned by editing"
            )
        self.content = parsed.model_dump_json()
        self.save(update_fields=["content", "updated_at"])
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


# ── Signals scout (headless cross-source explorer) ──────────────────────────────
#
# Three tables back the v1 Signals scout:
#   - SignalScoutConfig: per-team binding (one row per team).
#   - SignalScoutRun:    bridge from a `tasks.TaskRun` to its scout-domain context.
#                        Mirrors `SignalReportTask` (1:1 to TaskRun instead of N:1
#                        to Task because scout runs are per-execution, not per-task).
#                        Status, timing, error, chat-log all live on `TaskRun`;
#                        findings live on emitted `Signal`/`SignalReport` rows.
#   - SignalScratchpad:  working notes the scout reads in future runs.


class SignalScoutConfig(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """One row per (team, scout skill): schedule + emit posture for a `signals-scout-*` skill.

    Changes are activity-logged (they drive spend). Team-level participation in the
    dogfood program is gated by the `signals-scout` flag at the coordinator, not here.
    """

    # ModelActivityMixin only logs deletes when this is set.
    activity_logging_on_delete = True

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
    enabled = models.BooleanField(default=True, db_default=True)
    # Dry-run vs emit. Defaults emit-on so a freshly authored scout is live from its first
    # tick. Flip to False for dry-run — the scout runs and logs but `emit_finding` writes
    # nothing — to validate it on a team before its findings reach the inbox.
    emit = models.BooleanField(default=True, db_default=True)
    # Minutes between runs. The coordinator dispatches this scout when
    # `last_run_at is None or now - last_run_at >= run_interval_minutes`. Deterministic —
    # no sampling. Floor of 30 keeps one scout from monopolising the worker pool and matches the
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
    # Stamped by the coordinator after each dispatch; drives the due-check. Written every
    # run, so it is excluded from activity logging (see field_exclusions below).
    last_run_at = models.DateTimeField(null=True, blank=True)
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

    class Meta:
        verbose_name = "Signal scout config"
        verbose_name_plural = "Signal scout configs"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "skill_name"], name="unique_scout_config_per_team_skill"),
        ]

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Signal scout run"
        verbose_name_plural = "Signal scout runs"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(fields=["team", "skill_name"], name="signal_scout_run_skill_idx"),
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Signal scratchpad"
        verbose_name_plural = "Signal scratchpads"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name="signal_scratchpad_unique_team_key"),
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
