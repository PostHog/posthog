"""Trigger handling for the PostHog Code Linear agent.

Turns a parsed Linear webhook trigger into a PostHog Code task: resolves the installing
integration, gates on the rollout flag, picks a repository, creates the task + run,
records the issue↔task mapping, starts the processing workflow, and acks on the Linear
issue. Runs inside the ``process_linear_agent_event`` Celery task.
"""

from typing import Any

from django.conf import settings
from django.db import IntegrityError

import structlog

from posthog.git import extract_explicit_repo
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.tasks.backend.logic.linear_agent.client import LinearAgentApiError, LinearAgentClient
from products.tasks.backend.logic.linear_agent.feature_flags import linear_agent_enabled
from products.tasks.backend.logic.linear_agent.parsing import LinearAgentTrigger, parse_agent_trigger
from products.tasks.backend.models import LinearIssueTaskMapping, Task

logger = structlog.get_logger(__name__)

RECONNECT_INTEGRATION_MESSAGE = (
    "I can't start work on this issue because the PostHog user who installed the Linear "
    "integration no longer exists. Reconnect the integration in PostHog settings and try again."
)
TASK_CREATION_FAILED_MESSAGE = (
    "Sorry — I couldn't create a PostHog Code task for this issue. "
    "Check the Linear integration in your PostHog settings and try again."
)
WORKFLOW_START_FAILED_MESSAGE = (
    "Sorry — I created a PostHog Code task for this issue but couldn't start it. Reassign the issue to me to try again."
)


def handle_linear_agent_event(payload: dict[str, Any]) -> None:
    """Process one verified, deduplicated Linear webhook payload."""
    trigger = parse_agent_trigger(payload)
    if trigger is None:
        return

    integration = _resolve_integration(trigger.organization_id)
    if integration is None:
        logger.info("linear_agent_no_integration_for_org", organization_id=trigger.organization_id)
        return

    if not linear_agent_enabled(integration):
        logger.info(
            "linear_agent_flag_disabled",
            integration_id=integration.id,
            team_id=integration.team_id,
        )
        return

    client = LinearAgentClient(integration)

    if trigger.agent_session_id:
        # Linear marks agent sessions unresponsive after ~10s without an activity — ack
        # before doing anything slow.
        _safe_agent_activity(
            client, trigger.agent_session_id, "Looking at this issue — setting up a PostHog Code task."
        )

    user = integration.created_by
    if user is None:
        _safe_comment(client, trigger.issue_id, RECONNECT_INTEGRATION_MESSAGE)
        return

    team = integration.team

    existing = (
        LinearIssueTaskMapping.objects.for_team(team.id)
        .filter(integration=integration, linear_issue_id=trigger.issue_id)
        .first()
    )
    if existing is not None:
        # Repeat assignment stays silent; a fresh @mention on an already-tracked issue
        # gets a pointer to the existing task instead of a duplicate.
        if trigger.kind == "mentioned":
            _safe_comment(
                client,
                trigger.issue_id,
                f"I'm already on this issue — follow along in PostHog Code: {_task_url(team.id, existing.task_id)}",
            )
        return

    description = trigger.issue_description
    if description is None:
        # Notification payloads carry a compact issue shape; fetch the full description
        # so the agent sees what the issue author wrote. Best-effort.
        try:
            description = client.get_issue_description(trigger.issue_id)
        except LinearAgentApiError:
            logger.warning(
                "linear_agent_issue_description_fetch_failed",
                integration_id=integration.id,
                linear_issue_id=trigger.issue_id,
            )

    repository = _resolve_repository(team, user.id, trigger, description)

    try:
        task = Task.create_and_run(
            team=team,
            title=_build_title(trigger),
            description=_build_task_description(trigger, description),
            origin_product=Task.OriginProduct.LINEAR,
            user_id=user.id,
            repository=repository,
            create_pr=True,
            mode="background",
            # The mapping row must exist before the workflow starts, or the agent could
            # finish and try to report back before the mapping does (Slack app precedent).
            start_workflow=False,
            posthog_mcp_scopes="full",
            interaction_origin="linear",
        )
    except Exception:
        logger.exception(
            "linear_agent_task_creation_failed",
            integration_id=integration.id,
            team_id=team.id,
            linear_issue_id=trigger.issue_id,
        )
        _safe_comment(client, trigger.issue_id, TASK_CREATION_FAILED_MESSAGE)
        return

    run = task.latest_run
    if run is None:
        logger.error("linear_agent_task_created_without_run", task_id=str(task.id), team_id=team.id)
        return

    try:
        LinearIssueTaskMapping.objects.for_team(team.id).create(
            team=team,
            integration=integration,
            linear_organization_id=trigger.organization_id,
            linear_issue_id=trigger.issue_id,
            linear_issue_identifier=trigger.issue_identifier or "",
            linear_issue_url=trigger.issue_url or "",
            linear_agent_session_id=trigger.agent_session_id,
            task=task,
            task_run=run,
        )
    except IntegrityError:
        # A concurrent duplicate delivery won the race; its task is the canonical one.
        # Ours was never started and nothing references it, so remove it.
        logger.info("linear_agent_duplicate_mapping_race", task_id=str(task.id), linear_issue_id=trigger.issue_id)
        task.delete()
        return

    from products.tasks.backend.temporal.client import (  # noqa: PLC0415 — keep temporalio off the webhook import path
        execute_task_processing_workflow,
    )

    try:
        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=str(run.id),
            team_id=team.id,
            user_id=user.id,
            create_pr=True,
            posthog_mcp_scopes="full",
        )
    except Exception:
        # Without this, the mapping would silently swallow every future trigger for the
        # issue while pointing at a task whose workflow never started. Drop the mapping so
        # reassigning the issue works, and tell the user; the orphaned run is picked up by
        # the stale-queued-run reconciler.
        logger.exception(
            "linear_agent_workflow_start_failed",
            task_id=str(task.id),
            run_id=str(run.id),
            team_id=team.id,
            linear_issue_id=trigger.issue_id,
        )
        LinearIssueTaskMapping.objects.for_team(team.id).filter(task=task).delete()
        _safe_comment(client, trigger.issue_id, WORKFLOW_START_FAILED_MESSAGE)
        return

    _safe_comment(client, trigger.issue_id, _ack_body(team.id, task.id, repository))

    logger.info(
        "linear_agent_task_created",
        task_id=str(task.id),
        run_id=str(run.id),
        team_id=team.id,
        linear_issue_id=trigger.issue_id,
        repository=repository,
        trigger_kind=trigger.kind,
    )


def _resolve_integration(organization_id: str) -> Integration | None:
    """Find the linear-agent integration for a Linear organization.

    Multiple PostHog teams may install the same Linear workspace (the unique constraint
    is per-team) — the oldest install wins deterministically, mirroring the GitHub
    webhook's multi-team pragmatism.
    """
    integrations = list(
        Integration.objects.filter(kind="linear-agent", integration_id=organization_id)
        .select_related("team", "created_by")
        .order_by("id")[:2]
    )
    if not integrations:
        return None
    if len(integrations) > 1:
        logger.warning(
            "linear_agent_multiple_integrations_for_org",
            organization_id=organization_id,
            used_integration_id=integrations[0].id,
        )
    return integrations[0]


def _resolve_repository(team: Team, user_id: int, trigger: LinearAgentTrigger, description: str | None) -> str | None:
    """Pick a repository for the task without ever raising.

    Deterministic cascade only: an explicit ``owner/repo`` mention in the issue wins,
    then a single-candidate short-circuit. The LLM repo-selection agent is deliberately
    not run here — it boots a sandbox session, which is too heavy for a webhook-driven
    Celery task. ``None`` starts a repo-less task and the ack comment says so.
    """
    from products.tasks.backend.logic.repo_selection.agent import (  # noqa: PLC0415 — keep sandbox-session deps off the webhook import path
        _list_candidate_repos,
        resolve_team_github_integration,
    )

    try:
        github = resolve_team_github_integration(team.id, team=team, requester_user_id=user_id)
        if github is None:
            return None
        candidates = _list_candidate_repos(github, team.id)
        if not candidates:
            return None

        text = "\n".join(part for part in (trigger.issue_title, description, trigger.comment_body) if part)
        explicit = extract_explicit_repo(text, candidates)
        if explicit:
            return explicit
        if len(candidates) == 1:
            return candidates[0]
        return None
    except Exception:
        logger.warning("linear_agent_repo_resolution_failed", team_id=team.id, exc_info=True)
        return None


def _build_title(trigger: LinearAgentTrigger) -> str:
    title = trigger.issue_title or "Linear issue"
    if trigger.issue_identifier:
        title = f"{trigger.issue_identifier}: {title}"
    return title[:255]


def _build_task_description(trigger: LinearAgentTrigger, description: str | None) -> str:
    trigger_line = (
        "assigned to the PostHog Code agent"
        if trigger.kind == "assigned"
        else "where the PostHog Code agent was mentioned"
    )
    lines = [f"This task was created from a Linear issue {trigger_line}."]
    if trigger.actor_name:
        lines.append(f"Requested by: {trigger.actor_name}")

    issue_ref = trigger.issue_identifier or trigger.issue_id
    lines.extend(["", f"Linear issue: {issue_ref}"])
    if trigger.issue_url:
        lines.append(f"Issue URL: {trigger.issue_url}")
    lines.append(f"Title: {trigger.issue_title}")

    if description:
        lines.extend(["", "Issue description:", description])
    if trigger.comment_body:
        lines.extend(["", "Comment that triggered this task:", trigger.comment_body])

    lines.extend(["", "Implement the change described above and open a pull request."])
    return "\n".join(lines)


def _task_url(team_id: int, task_id: Any) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/tasks/{task_id}"


def _ack_body(team_id: int, task_id: Any, repository: str | None) -> str:
    lines = [f"On it! I created a PostHog Code task for this issue: {_task_url(team_id, task_id)}"]
    if repository:
        lines.append(f"Working in `{repository}`.")
    else:
        lines.append(
            "I couldn't determine which repository to use — mention it in the issue "
            "(e.g. `owner/repo`) and reassign me, or attach one to the task in PostHog Code."
        )
    return "\n".join(lines)


def _safe_comment(client: LinearAgentClient, issue_id: str, body: str) -> None:
    """Post a comment without letting Linear API failures abort event handling."""
    try:
        client.create_comment(issue_id, body)
    except LinearAgentApiError:
        logger.warning(
            "linear_agent_comment_failed",
            integration_id=client.integration.id,
            linear_issue_id=issue_id,
        )


def _safe_agent_activity(client: LinearAgentClient, agent_session_id: str, body: str) -> None:
    try:
        client.create_agent_activity(agent_session_id, body)
    except LinearAgentApiError:
        logger.warning(
            "linear_agent_session_ack_failed",
            integration_id=client.integration.id,
            agent_session_id=agent_session_id,
        )
