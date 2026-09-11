from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponse

import structlog

from posthog.api.github_webhooks.contracts import PullRequestAttribution
from posthog.api.github_webhooks.integrations import _SCOPE_DB_ALIAS, _installation_id, _installation_team_ids
from posthog.api.github_webhooks.metrics import GitHubWebhookAnalyticsEvent, observe_github_webhook_pr_event_dropped
from posthog.api.github_webhooks.pull_requests import capture_pr_event, pr_state_for_action
from posthog.event_usage import groups
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user_integration import UserIntegration

from products.signals.backend.facade.github import update_pull_request_assignments
from products.tasks.backend.constants import PR_LOOP_ENABLED_STATE_KEY
from products.tasks.backend.facade.api import post_pr_created_thread_update, signal_workflow_completion
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.metrics import observe_github_webhook_task_run_lookup
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.pr_urls import merge_pr_output, read_pr_urls
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PREFIX

logger = structlog.get_logger(__name__)

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

_TERMINAL_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def _run_repository_filter(repository: str) -> Q:
    normalized = repository.strip().lower()
    return Q(state__repositories__contains=[normalized]) | Q(
        state__repositories__isnull=True,
        task__repository__iexact=normalized,
    )


def find_task_run(
    pr_url: str | None = None,
    branch: str | None = None,
    repository: str | None = None,
    team_ids: list[int] | None = None,
) -> TaskRun | None:
    """Find the TaskRun a GitHub webhook belongs to, preferably scoped to ``team_ids``.

    Every leg below filters on a JSON containment or a plain ``branch`` value, none of which
    is indexed, so an unscoped lookup walks all of ``posthog_task_run`` three times per
    delivery. ``team_id`` is a plain FK and therefore already indexed: passing the teams the
    webhook's installation belongs to turns those walks into index scans. When the caller
    cannot resolve any team the old unscoped behaviour is kept, just counted.
    """
    repository = repository.strip() if repository else None

    observe_github_webhook_task_run_lookup(scoped=bool(team_ids))
    if not team_ids:
        logger.info("github_webhook_task_run_lookup_unscoped", pr_url=pr_url, branch=branch, repository=repository)

    candidates = TaskRun.objects.filter(team_id__in=team_ids) if team_ids else TaskRun.objects.all()
    # ReviewHog runs check out the PR head branch to review it, but they never author a PR, so no
    # leg below may return one. The exclusion belongs here rather than on each leg: a stale
    # ``verified_pr_urls`` claim, left on a ReviewHog run by an earlier wrong branch match, would
    # otherwise keep every later event for that PR on the reviewing run. Dropping the claim falls
    # through to the legs below, which resolve the run that authored the PR.
    candidates = candidates.exclude(task__origin_product=Task.OriginProduct.REVIEW_HOG)

    if pr_url:
        # A resumed wizard run inherits its predecessor's head branch, so a terminal
        # original and its live resume can both claim the same PR URL. Scope to the
        # webhook's repo and prefer non-terminal runs so merge handling lands on the
        # run that can still act on it.
        runs = candidates.filter(state__verified_pr_urls__contains=[pr_url])
        if repository:
            runs = runs.filter(_run_repository_filter(repository))
        # Declared type keeps mypy happy: the annotated queryset yields an AnnotatedWith
        # variant that must not leak into the plain-queryset legs below.
        task_run: TaskRun | None = (
            runs.annotate(
                terminal_rank=Case(
                    When(status__in=_TERMINAL_RUN_STATUSES, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("terminal_rank", "-created_at")
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

    # Branch-only lookups must be scoped to the repository the webhook came from.
    # Without this, a PR opened on an unrelated repo with a colliding branch name
    # (e.g. "main") gets attributed to whichever TaskRun shares that branch.
    if branch and repository:
        # A self-driving implementation run stamps its server-generated head branch into
        # PATCH-protected state (signals' auto_start). That stamp is the run->PR link no
        # caller can forge, so resolve it before the generic branch legs below. Without
        # this, a newer ReviewHog run whose checkout branch is the same head ref wins the
        # branch match and every later webhook, misattributing the PR's lifecycle events.
        # FAILED and CANCELLED runs and soft-deleted tasks are dropped; a COMPLETED run
        # stays eligible because success flips the run to COMPLETED right after it opens
        # the PR. The task_run_sd_branch_idx index covers this filter.
        task_run = (
            candidates.filter(
                _run_repository_filter(repository),
                state__self_driving_head_branch=branch,
                task__deleted=False,
            )
            .exclude(status__in=(TaskRun.Status.FAILED, TaskRun.Status.CANCELLED))
            .order_by("-created_at", "-id")
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

        # Wizard runs are excluded here: their `branch` column holds the checkout (base)
        # branch, so a same-repo PR whose head ref equals the base (e.g. "main") would
        # otherwise claim the run before the dedicated leg below is consulted.
        task_run = (
            candidates.filter(
                _run_repository_filter(repository),
                branch=branch,
                state__wizard_head_branch__isnull=True,
            )
            .order_by("-created_at", "-id")
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

        # Signed commits report every pushed repository/branch pair separately
        # from ``branch``. The latter controls provisioning's next checkout and
        # cannot represent nested repositories or multiple PR branches.
        head_branch = {"repository": repository.lower(), "branch": branch}
        task_run = (
            candidates.filter(
                _run_repository_filter(repository),
                output__head_branches__contains=[head_branch],
                state__wizard_head_branch__isnull=True,
            )
            .order_by("-created_at", "-id")
            .select_related(*TASK_RUN_SELECT_RELATED)
            .first()
        )
        if task_run:
            return task_run

        # Wizard cloud runs push to a server-generated head branch stored in run state.
        # The prefix check keeps this leg off the hot path for ordinary PR webhooks, and
        # terminal runs are excluded so a reopened branch can't fire events on a dead run
        # (post-merge events for bound runs resolve via the pr_url leg above).
        if branch.startswith(WIZARD_HEAD_BRANCH_PREFIX):
            task_run = (
                candidates.filter(
                    _run_repository_filter(repository),
                    state__wizard_head_branch=branch,
                    task__deleted=False,
                )
                .exclude(status__in=_TERMINAL_RUN_STATUSES)
                .select_related(*TASK_RUN_SELECT_RELATED)
                .first()
            )
            if task_run:
                return task_run

    return None


def _capture_task_pr_event(payload: dict, task_run: TaskRun | None, event: GitHubWebhookAnalyticsEvent) -> None:
    try:
        attribution = None
        if task_run is not None:
            attribution = PullRequestAttribution(
                source="task",
                team_id=task_run.team_id,
                distinct_id=(
                    str(task_run.task.created_by.distinct_id)
                    if task_run.task.created_by_id and task_run.task.created_by
                    else str(task_run.team.uuid)
                ),
                groups=groups(team=task_run.team),
                properties=task_run.analytics_properties(),
                include_content=True,
                send_feature_flags=True,
            )
    except Exception as error:
        observe_github_webhook_pr_event_dropped(analytics_event=event, reason="capture_exception")
        logger.warning("github_pr_webhook_capture_failed", analytics_event=event, error=str(error))
        return
    capture_pr_event(payload, attribution, event)


def handle_pull_request_event(payload: dict) -> HttpResponse:
    """Process a pre-verified pull_request webhook event.

    Called from the shared GitHub webhook dispatcher (unified dispatcher).
    """
    action = payload.get("action")
    pull_request = payload.get("pull_request", {})
    pr_url = pull_request.get("html_url")
    merged = pull_request.get("merged", False)

    if not pr_url:
        logger.warning("github_pr_webhook_no_pr_url", action=action)
        return HttpResponse(status=200)

    pr_state = pr_state_for_action(action, pull_request)
    analytics_event: GitHubWebhookAnalyticsEvent | None = None
    if action == "opened":
        event_action = "created"
        analytics_event = "pr_created"
    elif action == "closed":
        if merged:
            event_action = "merged"
            analytics_event = "pr_merged"
        else:
            event_action = "closed"
            analytics_event = "pr_closed"
    elif pr_state is not None:
        # A state-only transition (reopened, ready_for_review, converted_to_draft):
        # worth recording on the matched run so the pr: list filters stay honest,
        # not worth an analytics event.
        event_action = action or ""
    else:
        logger.debug("github_pr_webhook_ignored_action", action=action, pr_url=pr_url)
        return HttpResponse(status=200)

    branch = pull_request.get("head", {}).get("ref")
    repository_full_name = (payload.get("repository") or {}).get("full_name")
    scoped_team_ids = _task_run_scope_team_ids(payload)
    task_run = find_task_run(pr_url=pr_url, branch=branch, repository=repository_full_name, team_ids=scoped_team_ids)
    claimed_pr_urls = (
        read_pr_urls(task_run.output if isinstance(task_run.output, dict) else {}) if task_run is not None else []
    )

    logger.info(
        "github_pr_webhook_processed",
        action=action,
        event_action=event_action,
        pr_url=pr_url,
        pr_source="task" if task_run else "external",
        task_id=str(task_run.task_id) if task_run else None,
        run_id=str(task_run.id) if task_run else None,
    )

    # Backstop the agent-side PR detector: when we matched the run (by branch+repo)
    # but its output carries no PR URL yet, persist it so the inbox-notification
    # gate, CI follow-up loop, and later webhook lookups can resolve the PR.
    # Only trust the match when the PR originates from a branch in the installed
    # repo itself — never a fork. For fork PRs, head.ref is attacker-controlled
    # while repository.full_name stays the base repo, so a branch+repo match could
    # otherwise bind an unrelated PR to the run.
    head_repo_full_name = ((pull_request.get("head") or {}).get("repo") or {}).get("full_name")
    is_internal_branch = (
        head_repo_full_name is not None
        and repository_full_name is not None
        and head_repo_full_name.strip().lower() == repository_full_name.strip().lower()
    )
    if task_run is not None and is_internal_branch:
        _record_run_pr_url(task_run, pr_url)

    # After the backstop on purpose: a just-backfilled pr_url means the run now
    # claims this PR. Gated on the run's *primary* PR — output.pr_state describes
    # the PR the task APIs surface as output.pr_url, so a same-branch webhook for
    # a secondary or unrelated PR must not restate it.
    if (
        task_run is not None
        and pr_state is not None
        and isinstance(task_run.output, dict)
        and task_run.output.get("pr_url") == pr_url
    ):
        _record_run_pr_state(task_run, pr_state)

    update_pull_request_assignments(payload, pr_state)

    if analytics_event is not None:
        _capture_task_pr_event(payload, task_run, analytics_event)

    if action == "closed" and merged:
        # Only trust the merge for the run that actually claims this PR URL. The pr_url backstop
        # above already covers branch-matched internal PRs, so requiring equality here keeps a
        # same-branch webhook for a different PR from marking this run's PR as merged.
        if task_run and pr_url in claimed_pr_urls:
            _record_run_pr_merged(task_run)

    if action == "closed" and not merged:
        # Same trust rule as the merge branch: only the run that claims this PR URL.
        if task_run and pr_url in claimed_pr_urls:
            _cancel_wizard_run_on_close(task_run)

    return HttpResponse(status=200)


def handle_pull_request_review_event(payload: dict) -> HttpResponse:
    """Process a pre-verified pull_request_review webhook event.

    Called from the shared GitHub webhook dispatcher (unified dispatcher). Captures a
    ``pr_reviewed`` analytics event for human review submissions (approved,
    changes_requested, commented), attributed to the reviewer when their GitHub
    login resolves to an org member.
    """
    if payload.get("action") != "submitted":
        return HttpResponse(status=200)

    review = payload.get("review") or {}
    reviewer = review.get("user") or {}
    pull_request = payload.get("pull_request") or {}
    pr_url = pull_request.get("html_url")
    if not pr_url:
        logger.warning("github_pr_review_webhook_no_pr_url")
        return HttpResponse(status=200)

    # StampHog, ReviewHog, and CI apps review every self-driving PR, so without this
    # filter the event stream is mostly bots and the human review signal drowns.
    if (reviewer.get("type") or "").lower() == "bot":
        logger.debug("github_pr_review_webhook_bot_review_skipped", pr_url=pr_url)
        return HttpResponse(status=200)

    branch = (pull_request.get("head") or {}).get("ref")
    repository_full_name = (payload.get("repository") or {}).get("full_name")
    task_run = find_task_run(
        pr_url=pr_url, branch=branch, repository=repository_full_name, team_ids=_task_run_scope_team_ids(payload)
    )

    _capture_task_pr_event(payload, task_run, "pr_reviewed")

    logger.info(
        "github_pr_review_webhook_processed",
        pr_url=pr_url,
        review_state=review.get("state"),
        pr_source="task" if task_run else "external",
        run_id=str(task_run.id) if task_run else None,
    )
    return HttpResponse(status=200)


def _record_run_pr_url(task_run: TaskRun, pr_url: str) -> None:
    """Persist ``output.pr_url`` for a webhook-matched run when it isn't set yet.

    The agent server normally records the PR URL when it observes the agent open
    the PR. When that detection misses, a branch+repo webhook match is the
    backstop — without this the run is recognized for analytics but its
    ``output.pr_url`` stays empty, so inbox notifications, the CI follow-up loop,
    and later webhook lookups never resolve the PR.
    """
    recorded = _append_run_pr_url(task_run, pr_url)
    if not recorded and pr_url not in read_pr_urls(task_run.output):
        return
    post_pr_created_thread_update(task_run, pr_url)
    if not recorded:
        return
    from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keep the heavy facade module off the webhook import path
        _refresh_self_driving_quota_for_pr,
    )

    _refresh_self_driving_quota_for_pr(task_run, None)
    # Publish-only (no append_log): the S3 run log has a live writer — the agent is streaming
    # log batches at exactly this moment — and append_log's read-modify-write would race it.
    # Tolerant: a stream hiccup must not fail the webhook; clients recover on refetch.
    try:
        events = [task_run.build_progress_event("pr", "completed", "Opened pull request", "setup", detail=pr_url)]
        if (task_run.state or {}).get(PR_LOOP_ENABLED_STATE_KEY):
            events.append(task_run.build_progress_event("ci", "in_progress", "Keeping CI green", "setup"))
        for event in events:
            task_run.publish_stream_event(event)
        task_run.publish_stream_state_event()
    except Exception:
        logger.warning("github_pr_webhook_pr_events_failed", run_id=str(task_run.id), exc_info=True)


def _append_run_pr_url(task_run: TaskRun, pr_url: str) -> bool:
    try:
        with transaction.atomic():
            locked = TaskRun.objects.select_for_update().get(id=task_run.id)
            state = locked.state if isinstance(locked.state, dict) else {}
            existing_verified = state.get("verified_pr_urls")
            verified_pr_urls = list(
                dict.fromkeys([*(existing_verified if isinstance(existing_verified, list) else []), pr_url])
            )
            locked.state = {**state, "verified_pr_urls": verified_pr_urls}
            if pr_url in read_pr_urls(locked.output):
                locked.save(update_fields=["state", "updated_at"])
                task_run.state = locked.state
                task_run.output = locked.output
                return False
            locked.output = merge_pr_output(locked.output, {"pr_urls": [pr_url]})
            locked.save(update_fields=["state", "output", "updated_at"])
        task_run.state = locked.state
        task_run.output = locked.output
        return True
    except Exception:
        logger.warning("github_pr_webhook_record_pr_url_failed", run_id=str(task_run.id), exc_info=True)
        return False


def _record_run_pr_state(task_run: TaskRun, pr_state: str) -> None:
    """Persist ``output.pr_state`` on a state-changing PR webhook.

    Overwrites (a PR moves open → draft → merged), unlike the write-once
    ``_record_run_output_field``. Tolerant: a failure here must not fail the
    webhook (GitHub retries 5xx, and the event is already handled).
    """
    try:
        task_run.output = TaskRun.update_output_atomic(task_run.id, updates={"pr_state": pr_state})
    except Exception:
        logger.warning("github_pr_webhook_record_pr_state_failed", run_id=str(task_run.id), exc_info=True)


def _record_run_pr_merged(task_run: TaskRun) -> None:
    """Persist ``output.pr_merged`` when the run's PR is merged.

    Surfaces that gate on merge state (e.g. the pre-ingestion sample-data placeholder pointing at
    the wizard's setup PR) read it off the run's ``output``, which is the only PR state the task
    APIs expose.
    """
    if not _record_run_output_field(task_run, "pr_merged", True, "github_pr_webhook_record_pr_merged_failed"):
        return
    # Publish-only (no append_log), same rationale and failure tolerance as _record_run_pr_url.
    try:
        pr_url = task_run.output.get("pr_url") if isinstance(task_run.output, dict) else None
        task_run.publish_stream_event(
            task_run.build_progress_event("pr", "completed", "Pull request merged", "setup", detail=pr_url)
        )
        task_run.publish_stream_state_event()
    except Exception:
        logger.warning("github_pr_webhook_pr_merged_events_failed", run_id=str(task_run.id), exc_info=True)
    _complete_wizard_run_on_merge(task_run)


def _complete_wizard_run_on_merge(task_run: TaskRun) -> None:
    """Wind down a wizard cloud run's Temporal workflow once its PR merges.

    A wizard run's only deliverable is its setup PR; once that merges, nothing is left for the
    sandbox to do, yet without this signal the workflow idles until the sandbox TTL expires and
    the onboarding UI reports the run as running for hours. Best-effort: the webhook must stay
    2xx even if Temporal is unreachable or the workflow already finished.
    """
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if "wizard_config" not in state:
        return
    if task_run.environment != TaskRun.Environment.CLOUD:
        return
    if task_run.status in _TERMINAL_RUN_STATUSES:
        return

    def _signal() -> None:
        try:
            signal_workflow_completion(task_run.id, TaskRun.Status.COMPLETED, None)
        except Exception:
            logger.warning("github_pr_webhook_wizard_completion_signal_failed", run_id=str(task_run.id), exc_info=True)

    # The pr_merged write has committed by the time the caller's atomic block exits; on_commit
    # keeps the signal after that commit even if this path ever runs inside an outer transaction.
    transaction.on_commit(_signal)


def _cancel_wizard_run_on_close(task_run: TaskRun) -> None:
    """Cancel a wizard cloud run when its setup PR is closed without merging.

    Closing the setup PR is the user's clearest "I don't want this" signal, yet without this
    hook the workflow keeps the sandbox running until its TTL expires and the onboarding UI
    reports the run as in flight for hours. Scoped to wizard runs: closing a regular task
    run's PR is a normal review action owned by the CI follow-up loop. Best-effort: the
    webhook must stay 2xx even if Temporal is unreachable or the run just finished.
    """
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if "wizard_config" not in state:
        return
    if task_run.environment != TaskRun.Environment.CLOUD:
        return
    if task_run.status in _TERMINAL_RUN_STATUSES:
        return

    def _cancel() -> None:
        try:
            cancel_task_run(
                task_run.id,
                task_run.task_id,
                task_run.team_id,
                reason="Setup pull request was closed",
                source="pr_closed",
            )
        except Exception:
            logger.warning("github_pr_webhook_wizard_cancel_failed", run_id=str(task_run.id), exc_info=True)

    # cancel_task_run does a synchronous Temporal round-trip; on_commit keeps it out of any
    # open transaction and after the webhook's own writes have committed.
    transaction.on_commit(_cancel)


def _record_run_output_field(task_run: TaskRun, key: str, value: str | bool, failure_log_event: str) -> bool:
    """Idempotently merge ``{key: value}`` into a run's ``output`` JSON under a row lock.

    Returns True only when this call performed the write, so callers can fire follow-on
    side effects exactly once. Tolerant: a failure here must not fail the webhook (GitHub
    retries 5xx, and the event is already handled).
    """
    if isinstance(task_run.output, dict) and task_run.output.get(key):
        return False
    try:
        with transaction.atomic():
            locked = TaskRun.objects.select_for_update().get(id=task_run.id)
            output = locked.output if isinstance(locked.output, dict) else {}
            if output.get(key):
                return False
            locked.output = {**output, key: value}
            locked.save(update_fields=["output", "updated_at"])
        # Keep the in-memory instance consistent for the rest of this request.
        task_run.output = locked.output
        return True
    except Exception:
        logger.warning(failure_log_event, run_id=str(task_run.id), exc_info=True)
        return False


def _task_run_scope_team_ids(payload: dict) -> list[int]:
    """Teams to scope the TaskRun lookup to, or empty to leave the lookup unscoped.

    An installation reaches a team two ways. Team-level ``Integration`` rows are the obvious
    one. The other is a personal install: a task picks a ``UserIntegration`` through
    ``Task.github_user_integration``, which is deliberately unindexed, so the run cannot be
    reached from the integration side at all. Those tasks live in a team of the installing
    user's organization, so widening the scope to those teams keeps the run findable while
    every leg still runs as ``team_id IN (...)`` on the FK index.

    Accepted edge: a user who has since left the organization no longer widens the scope, so
    a delivery for a run they created that way stops matching. Anything with no installation
    id, or an installation nothing is linked to, falls back to the unscoped lookup.
    """
    external_id = _installation_id(payload)
    if external_id is None:
        return []

    team_ids = set(_installation_team_ids(payload))

    # Left lazy on purpose: Django inlines these as subqueries, so the whole widening is one
    # indexed round-trip rather than three.
    user_ids = (
        UserIntegration.objects.using(_SCOPE_DB_ALIAS)
        .filter(kind="github", integration_id=external_id)
        .values_list("user_id", flat=True)
    )
    org_ids = (
        OrganizationMembership.objects.using(_SCOPE_DB_ALIAS)
        .filter(user_id__in=user_ids)
        .values_list("organization_id", flat=True)
    )
    team_ids.update(
        Team.objects.using(_SCOPE_DB_ALIAS).filter(organization_id__in=org_ids).values_list("id", flat=True)
    )

    return sorted(team_ids)
