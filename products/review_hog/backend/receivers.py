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

The same resolved acting reviewer carries a second, independent toggle:
`stamphog_review_inbox_prs` sends the PR (the PR leg only — stamphog has nothing to publish to on
a bare branch) to hosted Stamphog for an approve-first review with a real GitHub approval, via the
stamphog facade (`queue_inbox_pr_review`). That call only queues the initial review; later pushes
re-review through stamphog's own webhook path, which re-checks this toggle through the resolver
registered in `connect()` (an inversion hook — stamphog can't import review_hog back without a
dependency cycle).

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

Kept import-light (django-startup-time): this module loads inside `AppConfig.ready()`, so the heavy
temporal-client and reviewer-resolution imports are deferred to call time.
"""

import json
import logging
from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.db.models.signals import post_save

from products.review_hog.backend.models import ReviewUserSettings
from products.signals.backend.models import SignalReportArtefact

# Deliberately import-light (it holds only the hook registry), so it can load here on ready().
from products.stamphog.backend.facade.inbox_hooks import register_inbox_acting_reviewer_resolver

logger = logging.getLogger(__name__)


def connect() -> None:
    """Wire the TaskRun-save receiver and the stamphog toggle hook; called once from `AppConfig.ready()`."""
    post_save.connect(
        handle_task_run_saved,
        sender=django_apps.get_model("tasks", "TaskRun"),
        dispatch_uid="review_hog_task_run_completed",
    )
    # Stamphog's webhook path re-checks the acting reviewer's stamphog toggle before every
    # re-review of a self-driving PR; it gets the resolver through this hook because importing
    # review_hog from stamphog would be a dependency cycle (this module already calls stamphog's
    # facade the other way).
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
        # Only the report's implementation task reviews. The pipeline's internal plumbing tasks
        # (report research, repo selection, custom agents) also carry signal_report_id but push
        # nothing — all created internal=True; the auto-start implementation task is the only
        # non-internal signal-report task.
        if task.internal:
            return
        repository = (task.repository or "").strip() or None
        if pr_url is None and repository is None:
            # The branch leg needs an explicit repo to compare in; the PR leg carries it in the URL.
            logger.info("review_hog_inbox_trigger_skipped: run %s has a branch target but no repository", instance.id)
            return
        acting_user_id = _resolve_assigned_reviewer(instance.team_id, task.signal_report_id, task.created_by_id)
        if acting_user_id is None:
            return
        settings = ReviewUserSettings.load(instance.team_id, acting_user_id)
        if settings.review_inbox_prs:
            transaction.on_commit(
                lambda: _start_review(
                    pr_url=pr_url,
                    repository=repository,
                    head_branch=head_branch,
                    team_id=instance.team_id,
                    user_id=acting_user_id,
                    signal_report_id=str(task.signal_report_id),
                )
            )
        if pr_url is not None and settings.stamphog_review_inbox_prs:
            # The PR leg only: stamphog's verdict is a GitHub review, so a bare pushed branch
            # gives it nothing to post to. The facade queues a Celery task, so the only work on
            # this save path is the broker publish.
            stamphog_pr_url = pr_url
            transaction.on_commit(
                lambda: _start_stamphog_review(
                    pr_url=stamphog_pr_url,
                    team_id=instance.team_id,
                    acting_user_id=acting_user_id,
                    signal_report_id=str(task.signal_report_id),
                    task_run_id=str(instance.id),
                )
            )
    except Exception:
        logger.exception("review_hog_inbox_trigger_failed")


def resolve_stamphog_acting_reviewer(team_id: int, signal_report_id: str, task_created_by_id: int | None) -> int | None:
    """The acting reviewer's user id when their stamphog inbox toggle is currently on, else None.

    Registered with stamphog's inbox hook registry (see `connect()`): stamphog's webhook path calls
    it before re-reviewing a self-driving PR on a later push, so switching the toggle off mid-PR
    stops new stamphog runs. Same acting-reviewer resolution as this module's own trigger.
    """
    acting_user_id = _resolve_assigned_reviewer(team_id, signal_report_id, task_created_by_id)
    if acting_user_id is None:
        return None
    if not ReviewUserSettings.load(team_id, acting_user_id).stamphog_review_inbox_prs:
        return None
    return acting_user_id


def _resolve_assigned_reviewer(team_id: int, signal_report_id: Any, task_created_by_id: int | None) -> int | None:
    """The assigned reviewer whose review options govern this run (no opt-in toggles checked here).

    Assignment = the report's **latest** `suggested_reviewers` artefact — the exact set the Inbox
    "For you" filter matches and Slack notifications fan out to — with logins resolved to org
    members the same way those surfaces resolve them. The acting reviewer is the task's own user
    (`created_by` — the auto-start assignee, or whoever clicked "Create PR") **when they are among
    the resolved reviewers**: someone who asked for the implementation gets their own rules applied
    to its review. Otherwise the **first** resolved reviewer is canonical (maintainer decisions,
    2026-07-02/03) — a background task whose creator carries no assignment meaning, or a
    non-assigned clicker, follows the primary assignee's rules. Their `review_inbox_prs` /
    `stamphog_review_inbox_prs` toggles gate the respective reviews (checked by the callers) and
    their ReviewHog options (perspectives / blind-spots / validator / urgency threshold) drive the
    ReviewHog one. Returns the acting reviewer's user id, or None when the report has no reviewers
    or none resolve to an org member.
    """
    # Deferred: the resolver module pulls posthog.schema (heavy) — keep it off django.setup().
    from products.signals.backend.report_generation.resolve_reviewers import (  # noqa: PLC0415
        resolve_org_github_login_to_users,
    )

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
        return None
    try:
        reviewers = json.loads(artefact.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(reviewers, list):
        return None
    logins = [
        str(r["github_login"]).strip().lower() for r in reviewers if isinstance(r, dict) and r.get("github_login")
    ]
    if not logins:
        return None
    login_to_user = resolve_org_github_login_to_users(team_id, logins)
    resolved = [login_to_user[login] for login in logins if login in login_to_user]
    if not resolved:
        return None
    acting = next((user for user in resolved if user.id == task_created_by_id), resolved[0])
    return acting.id


def _start_stamphog_review(
    *, pr_url: str, team_id: int, acting_user_id: int, signal_report_id: str, task_run_id: str
) -> None:
    """Fire-and-forget the hosted Stamphog review; the broker being down must never surface into the saver.

    Repo-config gating (a synced+enabled StamphogRepoConfig for the PR's repository) happens
    inside the queued task — teams without the Stamphog App get a silent no-op there, so this
    stays a plain toggle-gated dispatch.
    """
    # Deferred so django.setup() (which imports this module via ready()) doesn't pay for the
    # stamphog facade's model imports in every process; only the hook-registry module is light
    # enough to import at the top.
    from products.stamphog.backend.facade.api import queue_inbox_pr_review  # noqa: PLC0415

    try:
        queue_inbox_pr_review(
            team_id=team_id,
            pr_url=pr_url,
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
    strictly better target (publishable, and its head IS the pushed branch).
    """
    # Deferred so django.setup() (which imports this module via ready()) doesn't pay for the heavy
    # temporal package (temporalio + PyGithub + the sandbox stack) in every process — even types.py
    # is unreachable without executing the package __init__, which registers all activities.
    from products.review_hog.backend.temporal.client import start_review_pr_workflow  # noqa: PLC0415
    from products.review_hog.backend.temporal.types import TRIGGER_INBOX  # noqa: PLC0415

    if pr_url is not None:
        target_kwargs: dict[str, str] = {"pr_url": pr_url}
    else:
        target_kwargs = {"repository": repository or "", "head_branch": head_branch or ""}
    try:
        workflow_id = start_review_pr_workflow(
            team_id=team_id,
            user_id=user_id,
            publish=True,
            acting_user_id=user_id,
            trigger_source=TRIGGER_INBOX,
            signal_report_id=signal_report_id,
            **target_kwargs,
        )
        logger.info("review_hog_inbox_review_started: workflow %s for signal report %s", workflow_id, signal_report_id)
    except Exception:
        logger.exception("review_hog_inbox_review_start_failed")
