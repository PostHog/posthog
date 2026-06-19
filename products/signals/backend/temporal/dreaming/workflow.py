"""Per-team dreaming run: workflow + activities.

Two activities, each with a bounded timeout:

- ``instrumentation_cleanup_activity`` — resolves the team's GitHub repo, inspects PRs merged
  since the previous run, detects instrumentation gaps, and reconciles the singleton cleanup
  PR. Returns only a small result summary (counts + PR ref) — diffs never cross the activity
  boundary, they're fetched and discarded inside the activity, well under the ~2 MiB limit.
- ``generate_and_deliver_briefing_activity`` — gathers context, generates the three-item
  briefing via the LLM, and delivers it to the inbox + Slack. Returns the inbox report id.

The workflow runs them in sequence and tolerates a failure in either: a dreaming run should
degrade gracefully (a missing briefing or skipped PR is fine; the next night retries) rather
than fail the whole run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.models.integration import GitHubIntegration
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.temporal.dreaming.briefing import generate_briefing
from products.signals.backend.temporal.dreaming.delivery import deliver_briefing
from products.signals.backend.temporal.dreaming.enrollment import DREAMING_SKILL_NAME
from products.signals.backend.temporal.dreaming.run import (
    InstrumentationCleanupResult,
    gather_briefing_context,
    resolve_since_iso,
    run_instrumentation_cleanup,
    write_dismissal_learnings_to_memory,
)
from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.repo_selection.agent import resolve_team_github_integration

logger = logging.getLogger(__name__)


@dataclass
class RunDreamingInput:
    team_id: int


@dataclass
class InstrumentationCleanupActivityOutput:
    repository: str | None
    prs_inspected: int
    gaps_detected: int
    pr_action: str
    pr_number: int | None
    pr_url: str | None
    note: str


@dataclass
class BriefingActivityOutput:
    report_id: str | None
    slack_posted: bool
    item_count: int


@dataclass
class RunDreamingOutput:
    team_id: int
    cleanup: InstrumentationCleanupActivityOutput
    briefing: BriefingActivityOutput


def _previous_run_iso(team_id: int) -> str | None:
    config = (
        SignalScoutConfig.all_teams.filter(team_id=team_id, skill_name=DREAMING_SKILL_NAME)
        .values_list("last_run_at", flat=True)
        .first()
    )
    return config.isoformat() if config else None


def _run_cleanup_sync(team_id: int) -> InstrumentationCleanupResult:
    github = resolve_team_github_integration(team_id)
    # Only an app-installation GitHubIntegration has the PR-write surface the cleanup needs;
    # a user-token integration can't open the cleanup PR, so skip rather than fail.
    if not isinstance(github, GitHubIntegration):
        return InstrumentationCleanupResult(
            repository=None,
            prs_inspected=0,
            gaps_detected=0,
            pr_action="skipped",
            note="no GitHub integration for team",
        )
    # Pick the repository the same way the rest of signals does: the integration's resolved
    # repos. We use the top-starred repo as the default cleanup target — it's the team's
    # primary codebase in the common single-repo case.
    repository = github.get_top_starred_repository()
    if not repository:
        return InstrumentationCleanupResult(
            repository=None,
            prs_inspected=0,
            gaps_detected=0,
            pr_action="skipped",
            note="no repository resolved for team",
        )
    # `repository` from get_top_starred_repository is `owner/name`; the integration methods
    # accept either `name` or `owner/name`, so pass the bare repo name to match `organization()`.
    repo_name = repository.split("/", 1)[1] if "/" in repository else repository
    since_iso = resolve_since_iso(_previous_run_iso(team_id))
    return run_instrumentation_cleanup(github, repo_name, since_iso=since_iso)


@temporalio.activity.defn
@scoped_temporal()
async def instrumentation_cleanup_activity(input: RunDreamingInput) -> InstrumentationCleanupActivityOutput:
    async with Heartbeater():
        result = await database_sync_to_async(_run_cleanup_sync, thread_sensitive=False)(input.team_id)
    logger.info(
        "dreaming: instrumentation cleanup done",
        extra={
            "team_id": input.team_id,
            "repository": result.repository,
            "prs_inspected": result.prs_inspected,
            "gaps_detected": result.gaps_detected,
            "pr_action": result.pr_action,
        },
    )
    return InstrumentationCleanupActivityOutput(
        repository=result.repository,
        prs_inspected=result.prs_inspected,
        gaps_detected=result.gaps_detected,
        pr_action=result.pr_action,
        pr_number=result.pr_number,
        pr_url=result.pr_url,
        note=result.note,
    )


def _gather_context_sync(team_id: int) -> tuple[str, list[str]]:
    team = Team.objects.get(id=team_id)
    scout_skills = list(
        LLMSkill.objects.filter(
            team_id=team_id,
            name__startswith=SIGNALS_SCOUT_SKILL_PREFIX,
            is_latest=True,
            deleted=False,
        ).values_list("name", flat=True)
    )
    return team.name, scout_skills


@temporalio.activity.defn
@scoped_temporal()
async def generate_and_deliver_briefing_activity(input: RunDreamingInput) -> BriefingActivityOutput:
    async with Heartbeater():
        project_name, scout_skills = await database_sync_to_async(_gather_context_sync, thread_sensitive=False)(
            input.team_id
        )
        last_run_at_iso = await database_sync_to_async(_previous_run_iso, thread_sensitive=False)(input.team_id)
        context, dismissals = await database_sync_to_async(gather_briefing_context, thread_sensitive=False)(
            input.team_id, project_name, scout_skills, last_run_at_iso=last_run_at_iso
        )
        briefing = await generate_briefing(input.team_id, context)
        report_id, slack_posted = await database_sync_to_async(deliver_briefing, thread_sensitive=False)(
            input.team_id, briefing
        )
        # Soft memory write: durable "why users dismiss" learnings. No-ops if agent_memory
        # isn't available, so this never affects the briefing's delivery result.
        await write_dismissal_learnings_to_memory(input.team_id, dismissals)
    logger.info(
        "dreaming: briefing delivered",
        extra={"team_id": input.team_id, "report_id": report_id, "slack_posted": slack_posted},
    )
    return BriefingActivityOutput(report_id=report_id, slack_posted=slack_posted, item_count=len(briefing.items))


@temporalio.workflow.defn(name="run-dreaming")
class RunDreamingWorkflow:
    """Drives one team's nightly dreaming run: instrumentation cleanup, then briefing.

    Each phase is independently retried and independently tolerant of failure — a dreaming
    run that can't open a cleanup PR should still deliver a briefing, and vice versa.
    """

    @temporalio.workflow.run
    async def run(self, input: RunDreamingInput) -> RunDreamingOutput:
        cleanup = await self._run_cleanup(input)
        briefing = await self._run_briefing(input)
        return RunDreamingOutput(team_id=input.team_id, cleanup=cleanup, briefing=briefing)

    async def _run_cleanup(self, input: RunDreamingInput) -> InstrumentationCleanupActivityOutput:
        try:
            return await workflow.execute_activity(
                instrumentation_cleanup_activity,
                input,
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=2),
                # Single attempt: the cleanup PR reconcile performs GitHub writes, and a blind
                # retry could race the singleton guard. A failure is logged; next night retries.
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            workflow.logger.warning("dreaming: instrumentation cleanup failed", extra={"team_id": input.team_id})
            return InstrumentationCleanupActivityOutput(
                repository=None,
                prs_inspected=0,
                gaps_detected=0,
                pr_action="skipped",
                pr_number=None,
                pr_url=None,
                note="cleanup activity failed",
            )

    async def _run_briefing(self, input: RunDreamingInput) -> BriefingActivityOutput:
        try:
            return await workflow.execute_activity(
                generate_and_deliver_briefing_activity,
                input,
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception:
            workflow.logger.warning("dreaming: briefing generation failed", extra={"team_id": input.team_id})
            return BriefingActivityOutput(report_id=None, slack_posted=False, item_count=0)
