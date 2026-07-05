"""Temporal workflow that runs the opportunity solutions researcher and persists its findings as
a Notebook linked to the Opportunity. Single-activity (the heavy lifting is in the activity), and
non-retryable: a retry would double-spend web-search and LLM budget on a user-triggered run.

Triggered by the `research` action on OpportunityViewSet.
"""

from __future__ import annotations

import time
import datetime as dt

import structlog
import temporalio.common
import temporalio.activity
import temporalio.workflow
import temporalio.exceptions
from asgiref.sync import sync_to_async

from posthog.models import Team, User
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

from products.notebooks.backend.facade import api as notebooks
from products.pulse.backend.generation.prompts import sanitize_for_prompt
from products.pulse.backend.generation.research import run_research
from products.pulse.backend.generation.research_notebook import build_research_notebook
from products.pulse.backend.models import Opportunity
from products.pulse.backend.temporal.inputs import RESEARCH_OPPORTUNITY_WORKFLOW_NAME, ResearchOpportunityWorkflowInputs

logger = structlog.get_logger(__name__)

RESEARCH_ACTIVITY_START_TO_CLOSE_SECONDS = 20 * 60
RESEARCH_ACTIVITY_HEARTBEAT_TIMEOUT_SECONDS = 5 * 60


@temporalio.workflow.defn(name=RESEARCH_OPPORTUNITY_WORKFLOW_NAME)
class ResearchOpportunityWorkflow(PostHogWorkflow):
    inputs_cls = ResearchOpportunityWorkflowInputs

    @temporalio.workflow.run
    async def run(self, inputs: ResearchOpportunityWorkflowInputs) -> None:
        await temporalio.workflow.execute_activity(
            research_opportunity_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=RESEARCH_ACTIVITY_START_TO_CLOSE_SECONDS),
            heartbeat_timeout=dt.timedelta(seconds=RESEARCH_ACTIVITY_HEARTBEAT_TIMEOUT_SECONDS),
            # No retries: the researcher spends web-search and LLM budget, so a retry double-spends.
            retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
        )


@temporalio.activity.defn
async def research_opportunity_activity(inputs: ResearchOpportunityWorkflowInputs) -> None:
    team = await sync_to_async(_get_team, thread_sensitive=False)(inputs.team_id)
    if not team.organization.is_ai_data_processing_approved:
        # The API already gates this, but re-check: consent can be revoked between request and run.
        raise temporalio.exceptions.ApplicationError(
            "AI data processing not approved for this organization", non_retryable=True
        )
    opportunity = await sync_to_async(_get_opportunity, thread_sensitive=False)(inputs.team_id, inputs.opportunity_id)
    user = await User.objects.aget(id=inputs.user_id)
    goal = await sync_to_async(_resolve_goal, thread_sensitive=False)(opportunity)

    opportunity_context = _build_opportunity_context(opportunity, goal)

    started = time.monotonic()
    async with Heartbeater():
        result = await run_research(
            team=team,
            user=user,
            opportunity_context=opportunity_context,
            heartbeat=temporalio.activity.heartbeat,
        )
    duration_s = time.monotonic() - started

    notebook_content = build_research_notebook(opportunity=opportunity, goal=goal, report=result.report)
    text_content = result.report.problem_class or "Opportunity research"
    notebook = await sync_to_async(notebooks.create_notebook, thread_sensitive=False)(
        team.id,
        title=f"Research — {opportunity.title}"[:200],
        content=notebook_content,
        text_content=text_content,
        created_by_id=user.id,
        last_modified_by_id=user.id,
    )

    await sync_to_async(_persist_notebook_id, thread_sensitive=False)(
        inputs.team_id, inputs.opportunity_id, notebook.id
    )

    proposal_count = len(result.report.proposals)
    await sync_to_async(_report_research_completed, thread_sensitive=False)(
        user=user,
        opportunity=opportunity,
        duration_s=duration_s,
        web_call_count=result.web_call_count,
        internal_query_count=result.internal_query_count,
        proposal_count=proposal_count,
    )


def _get_team(team_id: int) -> Team:
    return Team.objects.select_related("organization").get(id=team_id)


def _get_opportunity(team_id: int, opportunity_id: str) -> Opportunity:
    return Opportunity.objects.for_team(team_id).select_related("first_seen_brief__config").get(id=opportunity_id)


def _resolve_goal(opportunity: Opportunity) -> str | None:
    brief = opportunity.first_seen_brief
    config = brief.config if brief is not None else None
    goal = (config.goal or "").strip() if config is not None else ""
    return goal or None


def _persist_notebook_id(team_id: int, opportunity_id: str, notebook_id: object) -> None:
    Opportunity.objects.for_team(team_id).filter(id=opportunity_id).update(research_notebook_id=notebook_id)


def _build_opportunity_context(opportunity: Opportunity, goal: str | None) -> str:
    lines = [
        f"Opportunity: {sanitize_for_prompt(opportunity.title)}",
        f"What was observed: {sanitize_for_prompt(opportunity.summary)}",
    ]
    if opportunity.suggested_action:
        lines.append(f"Suggested action: {sanitize_for_prompt(opportunity.suggested_action)}")
    if goal:
        lines.append(f"Focus goal this opportunity serves: {sanitize_for_prompt(goal)}")
    evidence = opportunity.evidence if isinstance(opportunity.evidence, list) else []
    labels = [
        sanitize_for_prompt(str(e.get("label") or "")) for e in evidence if isinstance(e, dict) and e.get("label")
    ]
    if labels:
        lines.append("Evidence backing it: " + "; ".join(labels))
    proposed = opportunity.proposed_experiment if isinstance(opportunity.proposed_experiment, dict) else None
    if proposed and proposed.get("hypothesis"):
        lines.append(
            f"An experiment was already proposed — hypothesis: {sanitize_for_prompt(str(proposed['hypothesis']))}"
        )
    return "\n".join(lines)


def _report_research_completed(
    *,
    user: User,
    opportunity: Opportunity,
    duration_s: float,
    web_call_count: int,
    internal_query_count: int,
    proposal_count: int,
) -> None:
    # ph_scoped_capture (not posthoganalytics.capture): outside request context the global client's
    # flush may never run before the worker moves on, silently losing the event.
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=user.distinct_id,
            event="opportunity_research_completed",
            properties={
                "opportunity_id": str(opportunity.id),
                "kind": opportunity.kind,
                "goal_relevant": opportunity.goal_relevant,
                "duration_s": round(duration_s, 1),
                "web_call_count": web_call_count,
                "internal_query_count": internal_query_count,
                "proposal_count": proposal_count,
            },
        )
