from __future__ import annotations

import json
from typing import TypedDict, TypeVar

from django.db import transaction

import structlog
from pydantic import BaseModel, ValidationError

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.signals.backend.report_generation.select_repo import RepoSelectionResult
from products.signals.backend.slack_inbox_notifications import POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME
from products.signals.backend.task_run_artefacts import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    record_implementation_task,
)
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

_M = TypeVar("_M", bound=BaseModel)


class ReviewerContent(TypedDict):
    github_login: str
    github_name: str | None
    relevant_commits: list[dict]


_PRIORITY_RANK: dict[Priority, int] = {
    Priority.P0: 0,
    Priority.P1: 1,
    Priority.P2: 2,
    Priority.P3: 3,
    Priority.P4: 4,
}


def _priority_rank(priority: Priority) -> int:
    return _PRIORITY_RANK[priority]


def _effective_threshold(config: SignalUserAutonomyConfig | None, team_default_priority: Priority) -> Priority:
    """A user's effective autostart threshold: their personal setting if set, else the team default."""
    return Priority(config.autostart_priority) if config and config.autostart_priority else team_default_priority


def _build_autostart_task_description(
    *, report_id: str, summary: str, repository: str, priority: PriorityAssessment | None
) -> str:
    priority_line = f"Priority: {priority.priority.value}\nReason: {priority.explanation}\n\n" if priority else ""
    report_deep_link = f"{POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME}://inbox/{report_id}"
    return (
        f"{summary}\n\n"
        f"{priority_line}"
        f"Repository: {repository}\n\n"
        "Address the symptom described above — not merely an adjacent issue you notice nearby. "
        "Investigate the root cause, implement the fix, and open a PR if appropriate. "
        "If your change fixes something related but does not change what the user actually observed, "
        "say so explicitly and stop rather than opening a PR for the wrong problem. "
        "For visual or UX symptoms (loading states, layout, flashes), reproduce the state or review a "
        "session recording of the affected flow to confirm your fix changes it — unit tests alone do not "
        "verify a visual symptom.\n\n"
        "You are acting fully autonomously on the user's behalf — there is no human approval step unless you "
        "explicitly request one. So before opening a PR against a repository the user does not own (any external "
        "/ third-party repo, not under the user's own org), check for the project's contribution and "
        "AI/LLM-authored-commit policies first. Look in the obvious places — CONTRIBUTING.md, the README, "
        "CODE_OF_CONDUCT.md, .github/ (including issue/PR templates), and any AGENTS.md, CLAUDE.md, ai.txt, or "
        "similarly named policy file — for rules on automated or AI-generated contributions, required disclosure, "
        "or PRs from non-collaborator forks. If the project forbids or restricts AI-authored PRs, requires a "
        "particular disclosure you can't satisfy, or the repo doesn't accept PRs from forks, do NOT open a PR "
        "against the upstream repo. Instead, push your branch to the user's own fork of the repository and point "
        "the user to that branch so they can review the changes and decide how to proceed, and explain in your "
        "turn summary why you didn't open the PR directly. Err on the side of caution to avoid committing a "
        "social faux pas in someone else's project.\n\n"
        "When opening the PR, include this report deep link in the description footer, "
        "making the footer '*Created with [PostHog Code](https://posthog.com/code?ref=pr) "
        f"from [an inbox report]({report_deep_link}).' - "
        "so the human reviewer can jump straight to it."
    )


def _create_implementation_task_if_absent(
    *,
    team_id: int,
    report_id: str,
    title: str,
    description: str,
    user_id: int,
    repository: str,
    base_branch: str | None,
) -> bool:
    """Create the implementation task and record it (gate row + work-log artefact), serialized per report.

    Auto-start is re-evaluated from several independent paths — the reviewer-edit on-commit hook,
    the agentic pipeline, and custom agents — so two evaluations can race. A bare check-then-create
    would let both observe "no implementation task yet" and each spawn one (duplicate Temporal
    workflow, duplicate draft PR, duplicate spend). Locking the `SignalReport` row and re-checking
    inside the lock makes the decision atomic: the second evaluation blocks, then sees the gate and
    returns ``False``. Returns ``True`` if it created the task, ``False`` if one already exists / the
    report is gone.
    """
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(id=report_id, team_id=team_id).first()
        if report is None:
            return False
        # The gate reads the unified task↔report view (`associated_task_runs` merges the legacy
        # `SignalReportTask` rows with the `task_run` artefact log). Unifying only *adds* sources,
        # so it can never under-detect a started implementation — and `record_implementation_task`
        # below always writes the `SignalReportTask` row, so deleting the (API-mutable) artefact
        # can't reopen the gate. Both writes happen under this lock, so a racing evaluation that
        # blocks here observes them and returns False.
        if SignalReport.associated_task_runs(
            report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        ):
            return False
        team = Team.objects.select_related("organization").get(id=team_id)
        created = tasks_facade.create_and_run_task(
            team=team,
            # "Implementation: <report title>" mirrors the research task's "Research: <report title>"
            # relabel, so the Runs surface reads "<relationship>: <report>" for every pipeline run.
            title=f"Implementation: {title}",
            description=description,
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            user_id=user_id,
            repository=repository,
            branch=base_branch,
            signal_report_id=report_id,
            # Full scopes so the implementation agent can log its work on the report (notes,
            # code references) via the task:write artefact tools.
            posthog_mcp_scopes="full",
            interaction_origin="signal_report",  # Makes the agent auto-push and open a draft PR
            ai_stage="implementation",
            # Keep pipeline-spawned implementation runs out of the default task list — the report
            # detail surfaces them by id (via task_run artefacts) and shows the draft PR there, so
            # listing them alongside user-created tasks is just noise. `internal` gates default list
            # visibility only, not access: retrieve-by-id, PR-url lookup, notifications, and the
            # `internal=all` Runs tab are all unaffected.
            internal=True,
        )
        if created.latest_run is None:
            raise RuntimeError(f"Task {created.task_id} auto-started without producing a TaskRun")
        # Written inside the lock so the gate check above and this write are serialized — the
        # `SignalReportTask` gate row must be visible before the lock releases.
        record_implementation_task(
            team_id=team_id,
            report_id=report_id,
            task_id=str(created.task_id),
            run_id=str(created.latest_run.id),
        )
        return True


def _resolve_autostart_assignee(
    team_id: int,
    report_priority: Priority,
    reviewers_content: list[ReviewerContent],
    team_default_priority: Priority,
) -> User | None:
    """Return the first suggested reviewer whose effective priority threshold allows auto-start.

    Only used for trusted (pipeline / custom-agent / scout) reviewer lists, which are derived from
    commit authorship rather than user input. User-triggered auto-start does not resolve a named
    reviewer at all — it runs as the triggering user (see `_resolve_triggering_user`), so a user
    can't name a colleague and have the agent run under that colleague's identity.

    Walks *reviewers_content* in order (most relevant first). A reviewer's effective threshold is
    their personal autonomy setting when present, otherwise the team default (itself "all
    priorities"/P4 when the team has no config row). A lower rank means higher priority. Returns
    the first matching ``User``, or ``None`` if no reviewer maps to an org member.
    """
    login_to_user = resolve_org_github_login_to_users(
        team_id, (str(r["github_login"]) for r in reviewers_content if r.get("github_login"))
    )
    report_rank = _priority_rank(report_priority)

    # Map reviewer github logins to org members, preserving reviewer order (most relevant first).
    candidate_users: list[User] = []
    for reviewer in reviewers_content:
        login = reviewer.get("github_login")
        if not login:
            continue
        candidate = login_to_user.get(login.lower())
        if isinstance(candidate, User):
            candidate_users.append(candidate)

    if not candidate_users:
        return None

    # Personal autonomy configs are optional: load any that exist to honor a reviewer's own
    # threshold. A reviewer with no config falls back to the team default, which is itself
    # "all priorities" (P4) when the team has no config row (set by the caller).
    configs = {
        c.user_id: c for c in SignalUserAutonomyConfig.objects.filter(user_id__in=[u.id for u in candidate_users])
    }

    for user in candidate_users:
        if report_rank <= _priority_rank(_effective_threshold(configs.get(user.id), team_default_priority)):
            return user

    return None


def _resolve_triggering_user(
    team_id: int,
    user_id: int,
    report_priority: Priority,
    team_default_priority: Priority,
) -> User | None:
    """Assignee for a *user-triggered* auto-start: the triggering user runs it as themselves.

    When a human edits a report's `suggested_reviewers` (the artefact API), that edit re-runs
    auto-start — but the agent mints a PostHog OAuth token under the task's user, so it must run as
    the person who triggered it, never as a named colleague (that would be reviewer impersonation).
    Returns the triggering user if they're an org member and their effective autonomy threshold
    allows the report's priority, else ``None``.
    """
    user = User.objects.filter(id=user_id, organization__team=team_id).first()
    if user is None:
        return None
    config = SignalUserAutonomyConfig.objects.filter(user_id=user_id).first()
    if _priority_rank(report_priority) <= _priority_rank(_effective_threshold(config, team_default_priority)):
        return user
    return None


async def maybe_autostart_implementation_task(
    *,
    team_id: int,
    report_id: str,
    repository: str,
    title: str,
    summary: str,
    actionability: ActionabilityAssessment,
    reviewers_content: list[ReviewerContent],
    priority: PriorityAssessment | None,
    triggering_user_id: int | None = None,
) -> None:
    """Start an implementation Task for a SignalReport if autonomy + priority allow it.

    ``triggering_user_id`` is set when a *user edit* of the report's `suggested_reviewers` re-ran
    auto-start: the task then runs as that user (they triggered it), never as a named colleague —
    the agent mints a PostHog OAuth token under the task's user, so running as the assignee would
    let one user act as another (reviewer impersonation). When ``None`` (the pipeline / custom
    agent / scout, whose reviewers come from commit authorship), the assignee is resolved from
    *reviewers_content*.

    Idempotent: skipped if an implementation task already started for the report
    (a `SignalReportTask` implementation gate row), if the report is not immediately
    actionable, if it's already addressed, if priority is missing, if there are no
    suggested reviewers, or if no reviewer qualifies. The
    "already started" check is enforced atomically under a row lock in
    `_create_implementation_task_if_absent`, so concurrent evaluations
    (reviewer-edit hook, pipeline, custom agent) can't double-start.

    Both the agentic signals pipeline (``temporal/agentic/report.py``) and the
    custom agent activity (``temporal/custom_agent.py``) call this after persisting
    their report and artefacts. Callers should wrap this in try/except so an
    autostart failure does not fail the report itself.
    """
    # Cheap pre-check to skip the expensive assignee resolution when a task already exists;
    # the authoritative, race-free check happens under the lock below.
    task_exists = bool(
        await SignalReport.aassociated_task_runs(
            report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        )
    )
    skip_reason: str | None = None
    if task_exists:
        skip_reason = "implementation task already exists"
    elif actionability.actionability != ActionabilityChoice.IMMEDIATELY_ACTIONABLE:
        skip_reason = f"not immediately actionable: {actionability.actionability.value}"
    elif actionability.already_addressed:
        skip_reason = "report already addressed"
    elif priority is None:
        skip_reason = "no priority assessment"
    elif not reviewers_content:
        skip_reason = "no suggested reviewers"
    if skip_reason is not None:
        logger.info("signals auto-start skipped", report_id=report_id, team_id=team_id, reason=skip_reason)
        return

    assert priority is not None  # narrowed by the `priority is None` skip_reason guard above

    team_config = await SignalTeamConfig.objects.filter(team_id=team_id).afirst()
    team_default_priority = Priority(team_config.default_autostart_priority) if team_config else Priority.P4

    # A user-triggered auto-start runs as the triggering user; otherwise resolve a trusted
    # (commit-authorship) reviewer. Either way the task's user is never an attacker-named colleague.
    if triggering_user_id is not None:
        task_user = await database_sync_to_async(_resolve_triggering_user, thread_sensitive=False)(
            team_id, triggering_user_id, priority.priority, team_default_priority
        )
    else:
        task_user = await database_sync_to_async(_resolve_autostart_assignee, thread_sensitive=False)(
            team_id, priority.priority, reviewers_content, team_default_priority
        )
    if task_user is None:
        logger.info(
            "signals auto-start skipped",
            report_id=report_id,
            team_id=team_id,
            reason="no reviewer meets the autonomy priority threshold",
        )
        return

    base_branch = None
    if repository and team_config:
        base_branch = (team_config.autostart_base_branches or {}).get(repository.lower())

    created = await database_sync_to_async(_create_implementation_task_if_absent, thread_sensitive=False)(
        team_id=team_id,
        report_id=report_id,
        title=title,
        description=_build_autostart_task_description(
            report_id=report_id, summary=summary, repository=repository, priority=priority
        ),
        user_id=task_user.id,
        repository=repository,
        base_branch=base_branch,
    )
    if not created:
        # Another evaluation won the race and already created the implementation task.
        logger.info("signals auto-start skipped", report_id=report_id, team_id=team_id, reason="lost create race")
        return


async def _latest_artefact_as(report_id: str, artefact_type: str, model_cls: type[_M]) -> _M | None:
    """Parse the latest artefact of ``artefact_type`` for a report (append-only, latest-wins)."""
    artefact = (
        await SignalReportArtefact.objects.filter(report_id=report_id, type=artefact_type)
        .order_by("-created_at")
        .afirst()
    )
    if artefact is None:
        return None
    try:
        return model_cls.model_validate_json(artefact.content)
    except ValidationError:
        return None


async def _latest_reviewers_content(report_id: str) -> tuple[list[ReviewerContent], int | None]:
    """Latest suggested-reviewers list, plus the id of the user who last edited it (if any).

    The second value is the artefact's user attribution (``created_by_id``): set when a human
    edited it via the artefact API, ``None`` when the pipeline/system wrote it. A user-edited list
    must auto-start as that user, never as a named colleague (reviewer impersonation).
    """
    artefact = (
        await SignalReportArtefact.objects.filter(
            report_id=report_id, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
        )
        .order_by("-created_at")
        .afirst()
    )
    if artefact is None:
        return [], None
    editor_user_id = artefact.created_by_id
    try:
        data = json.loads(artefact.content)
    except (json.JSONDecodeError, ValueError):
        return [], editor_user_id
    if not isinstance(data, list):
        return [], editor_user_id
    reviewers: list[ReviewerContent] = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("github_login"):
            reviewers.append(
                ReviewerContent(
                    github_login=str(entry["github_login"]),
                    github_name=entry.get("github_name"),
                    relevant_commits=entry.get("relevant_commits") or [],
                )
            )
    return reviewers, editor_user_id


async def maybe_autostart_from_report_artefacts(*, team_id: int, report_id: str) -> None:
    """Re-evaluate auto-start from a report's *current* artefacts.

    Called when reviewers change after the report was created (e.g. a human edits them via the
    artefact API), so a newly-qualifying reviewer can still trigger auto-start. Reconstructs the
    latest actionability / priority / repo-selection / suggested-reviewers and delegates to
    `maybe_autostart_implementation_task`, which is idempotent — it no-ops if an implementation
    task already exists for the report.

    When the latest reviewers artefact was user-edited, the task runs as that editing user (not a
    named colleague) — see `_latest_reviewers_content` and `triggering_user_id`.
    """
    report = await SignalReport.objects.filter(id=report_id, team_id=team_id).only("title", "summary").afirst()
    if report is None or not report.title or not report.summary:
        logger.info(
            "signals auto-start re-eval skipped",
            report_id=report_id,
            team_id=team_id,
            reason="report missing or not yet summarized",
        )
        return

    actionability = await _latest_artefact_as(
        report_id, SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT, ActionabilityAssessment
    )
    if actionability is None:
        logger.info(
            "signals auto-start re-eval skipped",
            report_id=report_id,
            team_id=team_id,
            reason="no actionability artefact",
        )
        return
    repo_selection = await _latest_artefact_as(
        report_id, SignalReportArtefact.ArtefactType.REPO_SELECTION, RepoSelectionResult
    )
    repository = repo_selection.repository if repo_selection else None
    if not repository:
        logger.info(
            "signals auto-start re-eval skipped",
            report_id=report_id,
            team_id=team_id,
            reason="no repository selected",
        )
        return
    priority = await _latest_artefact_as(
        report_id, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT, PriorityAssessment
    )
    reviewers_content, editor_user_id = await _latest_reviewers_content(report_id)
    if not reviewers_content:
        logger.info(
            "signals auto-start re-eval skipped",
            report_id=report_id,
            team_id=team_id,
            reason="no suggested reviewers",
        )
        return

    await maybe_autostart_implementation_task(
        team_id=team_id,
        report_id=report_id,
        repository=repository,
        title=report.title,
        summary=report.summary,
        actionability=actionability,
        reviewers_content=reviewers_content,
        priority=priority,
        # If a user edited the reviewers, run the task as that user — never as a named colleague,
        # which would let one user act under another's PostHog identity (reviewer impersonation).
        triggering_user_id=editor_user_id,
    )
