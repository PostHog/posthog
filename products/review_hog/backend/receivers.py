"""The inbox trigger: auto-review self-driving (Signals) implementations when they produce a PR.

A `post_save` receiver on `tasks.TaskRun` (resolved via the app registry — tasks never imports
review_hog, keeping every product edge in the existing direction). The trigger is the save that
records a review target on the run's `output` — NOT run completion: on the tasks architecture a
successful run deliberately never leaves `in_progress` (it stays followable and the PR follow-up
loop babysits the PR; see `execute_sandbox/workflow.py::_maybe_record_terminal_status`), so a
completion-gated trigger would never fire. The review is gated by the **report's assignees**: the
users the Inbox "For you" filter and its Slack notifications resolve from the report's latest
`suggested_reviewers` artefact. The acting reviewer — whose `review_inbox_prs` gates the review
and whose perspectives / validator / urgency threshold drive it — is the task's own user when they
are among the assigned reviewers (whoever clicked "Create PR", or the auto-start assignee), else
the first assigned reviewer that resolves to an org member. `Task.created_by` alone carries no
assignment meaning (background signals tasks are created as the GitHub-integration creator), which
is why it only counts when it maps into the assigned set.

The assigned reviewers carry a second, independent toggle: `stamphog_review_inbox_prs` sends the PR
to hosted Stamphog for an approve-first review with a real GitHub approval, through the stamphog
facade (`queue_inbox_pr_review`). Only when there is a PR, because stamphog's verdict is a GitHub
review and a bare pushed branch gives it nothing to post to. Any assigned reviewer's opt-in is
enough, unlike the acting-reviewer gate above: stamphog reads no per-user options, so narrowing it
to one reviewer would only drop reviews the other assignees asked for. That call queues the first
review only; later pushes are re-reviewed by stamphog's own webhook path, which re-checks the same
toggle through the resolver registered in `connect()` (stamphog cannot import review_hog back
without a dependency cycle).

Review targets, in priority order:
- `output.pr_url` → the PR leg: full review, published to the PR. Written by the agent server when
  it observes the agent open the PR, or by the GitHub-webhook backstop (`tasks/webhooks.py`).
- `output.head_branch` → the branch leg: the pushed work branch, synced by the agent server at the
  end of every agent turn whose current branch changed (`syncCloudBranchMetadata`). The review is
  computed and stored (receipt `outcome="stored"`); there is no PR to publish to. When the PR opens
  later, the `pr_url` save re-fires this receiver and the branch-keyed review upgrades to the PR —
  resume at the same head skips recompute and goes straight to publish.

The `TaskRun.branch` FIELD is never used as a target: auto-start seeds it with the BASE branch and
the agent server later overwrites it with the work branch, so its meaning depends on the path taken.

"""

import json
import logging
from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.db.models.signals import post_save

from products.review_hog.backend.models import ReviewUserSettings
from products.signals.backend.models import SignalReportArtefact
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.stamphog.backend.facade.inbox_hooks import register_inbox_acting_reviewer_resolver

# This module loads during django.setup() (AppConfig.ready() wires the receiver), and
# posthog/test/repo_invariants/test_startup_import_budget.py forbids temporalio/modal/openai/anthropic at setup —
# the temporal client and the stamphog task module reach all four, so those two imports stay
# function-local in _start_review / _start_stamphog_review per the budget test's own prescription.

logger = logging.getLogger(__name__)


def connect() -> None:
    """Wire the TaskRun-save receiver and the stamphog toggle hook; called once from `AppConfig.ready()`."""
    post_save.connect(
        handle_task_run_saved,
        sender=django_apps.get_model("tasks", "TaskRun"),
        dispatch_uid="review_hog_task_run_completed",
    )
    # Stamphog re-checks this toggle before re-reviewing a self-driving PR. It gets the resolver
    # through a hook because importing review_hog from stamphog would be a dependency cycle.
    register_inbox_acting_reviewer_resolver(resolve_stamphog_acting_reviewer)


def handle_task_run_saved(sender: type, instance: Any, created: bool, **kwargs: Any) -> None:
    """Start an inbox review when a signals-origin implementation run records a PR or pushed branch.

    Fires on every TaskRun save (a hot model), so the checks run cheapest-first and the whole body is
    exception-proof — this executes inside tasks' save path and must never raise into it. Repeat
    saves with an unchanged target re-fire it deliberately: the deterministic workflow id +
    USE_EXISTING collapse duplicates while a review runs, a same-head re-trigger costs one fetch
    (early-exit), and a transient base-branch `head_branch` self-skips on the empty diff.
    """
    try:
        if created:
            # Runs are created before the agent does anything; targets arrive via later saves.
            return
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "output" not in update_fields:
            # Declared-fields saves that don't touch `output` (follow-up state persistence,
            # status flips) can't carry a new review target — drop them without a DB hit.
            return
        if instance.status in (instance.Status.FAILED, instance.Status.CANCELLED):
            return
        output = instance.output if isinstance(instance.output, dict) else {}
        pr_url = output.get("pr_url") or None
        head_branch = output.get("head_branch") or None
        if pr_url is None and head_branch is None:
            return
        task = instance.task  # first DB hit
        if task.signal_report_id is None:
            return
        if task.deleted:
            # A soft-deleted task's run can still save output. Its PR is disowned work, and the
            # webhook leg already drops deleted tasks (find_signal_implementation_run), so the
            # first review must gate the same way instead of minting the approval the delete disavowed.
            return
        # Only the self-driving implementation run reviews. Report research and repo selection share
        # both signal_report_id and internal=True with it, so only ai_stage tells them apart.
        if (instance.state or {}).get("ai_stage") != "implementation":
            return
        repository = (task.repository or "").strip() or None
        if pr_url is None and repository is None:
            # The branch leg needs an explicit repo to compare in; the PR leg carries it in the URL.
            logger.info("review_hog_inbox_trigger_skipped: run %s has a branch target but no repository", instance.id)
            return
        resolved = _resolve_assigned_reviewers(instance.team_id, task.signal_report_id)
        if not resolved:
            return
        settings_by_user = ReviewUserSettings.load_many(instance.team_id, [user.id for user in resolved])
        acting_user_id = _pick_reviewer(resolved, task.created_by_id)
        stamphog_user_id = _pick_stamphog_reviewer(resolved, settings_by_user, task.created_by_id)
        # robust=True on both: the two dispatches are independent but share one commit-hook queue, so
        # a failure in one must not cancel the other. Django logs the failing hook and runs the rest.
        if settings_by_user[acting_user_id].review_inbox_prs:
            transaction.on_commit(
                lambda: _start_review(
                    pr_url=pr_url,
                    repository=repository,
                    head_branch=head_branch,
                    team_id=instance.team_id,
                    user_id=acting_user_id,
                    signal_report_id=str(task.signal_report_id),
                ),
                robust=True,
            )
        if pr_url is not None and stamphog_user_id is not None and repository is not None:
            # Only when there is a PR: stamphog posts a GitHub review, and a bare branch gives it
            # nothing to post to. Queuing a Celery task keeps this save path fast.
            stamphog_pr_url, stamphog_repository = pr_url, repository
            transaction.on_commit(
                lambda: _start_stamphog_review(
                    pr_url=stamphog_pr_url,
                    repository=stamphog_repository,
                    team_id=instance.team_id,
                    acting_user_id=stamphog_user_id,
                    signal_report_id=str(task.signal_report_id),
                    task_run_id=str(instance.id),
                ),
                robust=True,
            )
    except Exception:
        logger.exception("review_hog_inbox_trigger_failed")


def resolve_stamphog_acting_reviewer(team_id: int, signal_report_id: str, preferred_user_id: int | None) -> int | None:
    """A reviewer whose stamphog inbox toggle is currently on, else None.

    Registered with stamphog's inbox hook registry (see `connect()`). Stamphog calls it before
    re-reviewing a self-driving PR on a later push and again when the queued first review executes,
    so turning the toggle off mid-PR stops further stamphog runs. It has to gate the same way the
    initial trigger does: if one path fires on "any assigned reviewer opted in" and the other only
    on the canonical reviewer, a push would treat the PR as opted out and retract a standing
    approval while somebody is still opted in. ``preferred_user_id`` (the task's creator, or the
    reviewer a queued job was attributed to) wins while still opted in, keeping attribution stable.
    """
    resolved = _resolve_assigned_reviewers(team_id, signal_report_id)
    if not resolved:
        return None
    settings_by_user = ReviewUserSettings.load_many(team_id, [user.id for user in resolved])
    return _pick_stamphog_reviewer(resolved, settings_by_user, preferred_user_id)


def _pick_stamphog_reviewer(
    resolved: list[Any], settings_by_user: dict[int, ReviewUserSettings], preferred_user_id: int | None
) -> int | None:
    """The user id to attribute a stamphog inbox review to, or None when nobody is opted in.

    Any assigned reviewer's opt-in is enough, unlike the ReviewHog review which gates on the
    canonical reviewer's: stamphog reads no per-user options, so the id is provenance only and
    narrowing to one reviewer would drop reviews the other assignees asked for. Among the opted-in
    reviewers the pick follows the same preferred-else-first rule, so the same user is attributed
    on the first review and on later re-reviews. Either way there is one review per head: this
    returns a single id however many are opted in, and stamphog dedupes on (pull request, head sha).
    """
    opted_in = [user for user in resolved if settings_by_user[user.id].stamphog_review_inbox_prs]
    return _pick_reviewer(opted_in, preferred_user_id) if opted_in else None


def _pick_reviewer(resolved: list[Any], task_created_by_id: int | None) -> int:
    """The canonical reviewer out of a non-empty resolved list: the task's own user, else the first.

    The task's user (`created_by`: the auto-start assignee, or whoever clicked "Create PR") wins when
    they are among the resolved reviewers, so someone who asked for the implementation gets their own
    rules applied to its review. Otherwise the first resolved reviewer is canonical (maintainer
    decisions, 2026-07-02/03): a background task whose creator carries no assignment meaning, or a
    non-assigned clicker, follows the primary assignee's rules.
    """
    return next((user.id for user in resolved if user.id == task_created_by_id), resolved[0].id)


def _resolve_assigned_reviewers(team_id: int, signal_report_id: Any) -> list[Any]:
    """The report's assigned reviewers, in assignment order (no opt-in toggles checked here).

    Assignment means the report's latest `suggested_reviewers` artefact, the same set the Inbox "For
    you" filter matches and Slack notifications fan out to, with logins resolved to org members the
    same way those surfaces resolve them. Callers decide which of them gates what: ReviewHog runs
    under the canonical reviewer (`_pick_reviewer`, whose perspectives, blind spots, validator, and
    urgency threshold drive the review), stamphog under any who opted in (`_pick_stamphog_reviewer`).
    Empty when the report has no reviewers or none resolve to an org member.
    """
    artefact = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=signal_report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        )
        .order_by("-created_at")
        .first()
    )
    if artefact is None:
        return []
    try:
        reviewers = json.loads(artefact.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(reviewers, list):
        return []
    logins = [
        str(r["github_login"]).strip().lower() for r in reviewers if isinstance(r, dict) and r.get("github_login")
    ]
    if not logins:
        return []
    login_to_user = resolve_org_github_login_to_users(team_id, logins)
    return [login_to_user[login] for login in logins if login in login_to_user]


def _start_stamphog_review(
    *, pr_url: str, repository: str, team_id: int, acting_user_id: int, signal_report_id: str, task_run_id: str
) -> None:
    """Fire-and-forget the hosted Stamphog review; the broker being down must never surface into the saver.

    The queued task checks the repo config (a synced, enabled StamphogRepoConfig for the PR's
    repository), so teams without the Stamphog App get a silent no-op there and this stays a plain
    toggle-gated dispatch. `repository` is the task's own repo, which the queued task requires the
    PR to be in; `output.pr_url` is writable through the task-run API, so the PR alone isn't trusted.
    """
    # Function-local: pulls the stamphog task module (temporalio via its workflow client), which
    # the startup-import-budget test forbids at django.setup() — see the module-top comment.
    from products.stamphog.backend.facade.tasks import queue_inbox_pr_review  # noqa: PLC0415

    try:
        queue_inbox_pr_review(
            team_id=team_id,
            pr_url=pr_url,
            repository=repository,
            acting_user_id=acting_user_id,
            signal_report_id=signal_report_id,
            task_run_id=task_run_id,
        )
        logger.info("review_hog_stamphog_inbox_review_queued: pr %s for signal report %s", pr_url, signal_report_id)
    except Exception:
        logger.exception("review_hog_stamphog_inbox_review_queue_failed")


def _start_review(
    *,
    pr_url: str | None,
    repository: str | None,
    head_branch: str | None,
    team_id: int,
    user_id: int,
    signal_report_id: str,
) -> None:
    """Fire-and-forget the review workflow; Temporal being down must never surface into the saver.

    The PR leg wins when both targets are present — the client accepts exactly one, and a PR is the
    strictly better target (publishable, and its head IS the pushed branch). The PR leg also honors
    the busy-guard, the same refusal the trigger/resolve endpoints apply, so an inbox review never
    starts while this PR's resolution run is still committing to the branch.
    """
    # Function-local: importing the temporal client executes the review_hog temporal package, whose
    # activity registration reaches temporalio, modal, openai, and anthropic — all four forbidden at
    # django.setup() by the startup-import-budget test. See the module-top comment.
    from products.review_hog.backend.reviewer.tools.github_meta import PRParser  # noqa: PLC0415
    from products.review_hog.backend.temporal.client import start_review_pr_workflow, workflow_running  # noqa: PLC0415
    from products.review_hog.backend.temporal.types import TRIGGER_INBOX, resolve_pr_workflow_id  # noqa: PLC0415

    try:
        if pr_url is not None:
            # Busy-guard (CONTEXT.md): a published inbox review chains its own resolution, which
            # commits to the branch for minutes — starting a fresh review meanwhile races those
            # pushes and re-reviews threads mid-settlement. Only the PR leg needs it (resolution
            # needs a pr_url, so the branch leg can't collide); the chained hand-off starts
            # resolution as a child workflow, never through this path, so it stays exempt.
            pr_info = PRParser().parse_github_pr_url(pr_url)
            if workflow_running(
                resolve_pr_workflow_id(
                    team_id=team_id,
                    owner=str(pr_info["owner"]),
                    repo=str(pr_info["repo"]),
                    pr_number=int(pr_info["pr_number"]),
                )
            ):
                logger.info(
                    "review_hog_inbox_review_skipped_busy: resolution still running for %s (signal report %s)",
                    pr_url,
                    signal_report_id,
                )
                return
            workflow_id = start_review_pr_workflow(
                team_id=team_id,
                user_id=user_id,
                publish=True,
                acting_user_id=user_id,
                trigger_source=TRIGGER_INBOX,
                signal_report_id=signal_report_id,
                pr_url=pr_url,
            )
        else:
            workflow_id = start_review_pr_workflow(
                team_id=team_id,
                user_id=user_id,
                publish=True,
                acting_user_id=user_id,
                trigger_source=TRIGGER_INBOX,
                signal_report_id=signal_report_id,
                repository=repository or "",
                head_branch=head_branch or "",
            )
        logger.info("review_hog_inbox_review_started: workflow %s for signal report %s", workflow_id, signal_report_id)
    except Exception:
        logger.exception("review_hog_inbox_review_start_failed")
