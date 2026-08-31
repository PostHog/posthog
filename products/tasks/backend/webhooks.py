import hmac
import uuid
import hashlib
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.db import OperationalError, connections, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import HttpResponse

import structlog
import posthoganalytics
from social_django.models import UserSocialAuth

from posthog.event_usage import groups
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import InvalidStatusTransition, SignalReport
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.tasks.backend.constants import PR_LOOP_ENABLED_STATE_KEY
from products.tasks.backend.facade.api import post_pr_created_thread_update, signal_workflow_completion
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.metrics import (
    GitHubWebhookAnalyticsEvent,
    GitHubWebhookAttributionOutcome,
    observe_github_webhook_attribution,
    observe_github_webhook_pr_event_dropped,
    observe_github_webhook_task_run_lookup,
)
from products.tasks.backend.models import TaskRun
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
        # Wizard runs are excluded here: their `branch` column holds the checkout (base)
        # branch, so a same-repo PR whose head ref equals the base (e.g. "main") would
        # otherwise claim the run before the dedicated leg below is consulted.
        task_run = (
            candidates.filter(
                _run_repository_filter(repository),
                branch=branch,
                state__wizard_head_branch__isnull=True,
            )
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


def verify_github_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    """
    Verify the GitHub webhook signature using HMAC-SHA256.

    GitHub sends a signature in the X-Hub-Signature-256 header in the format:
    sha256=<hex_digest>
    """
    if not signature or not signature.startswith("sha256="):
        return False

    expected_signature = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected_signature, signature)


def get_github_webhook_secret() -> str | None:
    """Get the GitHub webhook secret from instance settings."""
    secret = get_instance_setting("GITHUB_WEBHOOK_SECRET")
    return secret if secret else None


def _pr_state_for_action(action: str | None, pull_request: dict) -> str | None:
    """The ``output.pr_state`` a webhook action moves a run's PR to, in the
    same open/draft/merged/closed vocabulary the GitHub snapshot uses. None
    for actions that don't change the state (comments, labels, pushes)."""
    if action in ("opened", "reopened"):
        return "draft" if pull_request.get("draft") else "open"
    if action == "ready_for_review":
        return "open"
    if action == "converted_to_draft":
        return "draft"
    if action == "closed":
        return "merged" if pull_request.get("merged") else "closed"
    return None


def handle_pull_request_event(payload: dict) -> HttpResponse:
    """Process a pre-verified pull_request webhook event.

    Called from ``posthog.urls.github_webhook`` (unified dispatcher).
    """
    action = payload.get("action")
    pull_request = payload.get("pull_request", {})
    pr_url = pull_request.get("html_url")
    merged = pull_request.get("merged", False)

    if not pr_url:
        logger.warning("github_pr_webhook_no_pr_url", action=action)
        return HttpResponse(status=200)

    pr_state = _pr_state_for_action(action, pull_request)
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
    task_run = find_task_run(
        pr_url=pr_url, branch=branch, repository=repository_full_name, team_ids=_task_run_scope_team_ids(payload)
    )
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

    if analytics_event is not None:
        # Deterministic UUID dedupes duplicate webhook deliveries of the same PR action.
        event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:{analytics_event}"))
        _capture_pr_event(payload, task_run, analytics_event, event_uuid)

    if task_run and action == "closed" and merged:
        # Only trust the merge for the run that actually claims this PR URL. The pr_url backstop
        # above already covers branch-matched internal PRs, so requiring equality here keeps a
        # same-branch webhook for a different PR from marking this run's PR as merged.
        if pr_url in claimed_pr_urls:
            _record_run_pr_merged(task_run)
        # Ungated on the pr_url match above: unlike the run-bookkeeping calls, this keys off
        # task_id (reports_for_task_filter), not output.pr_url, so the same-branch trust rule
        # doesn't apply — a merged PR resolves its report.
        _transition_signal_reports_for_task(
            task_run.task_id, pr_url, SignalReport.Status.RESOLVED, "github_pr_webhook_signal_report_resolved"
        )

    if task_run and action == "closed" and not merged:
        # Same trust rule as the merge branch: only the run that claims this PR URL.
        if pr_url in claimed_pr_urls:
            _cancel_wizard_run_on_close(task_run)
        # Ungated for the same reason as the merge branch's resolve call: a closed-unmerged PR
        # archives (suppresses) its report so it leaves the inbox instead of lingering.
        _transition_signal_reports_for_task(
            task_run.task_id, pr_url, SignalReport.Status.SUPPRESSED, "github_pr_webhook_signal_report_archived"
        )

    return HttpResponse(status=200)


def handle_pull_request_review_event(payload: dict) -> HttpResponse:
    """Process a pre-verified pull_request_review webhook event.

    Called from ``posthog.urls.github_webhook`` (unified dispatcher). Captures a
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

    # One review submission = one event; GitHub redeliveries collapse on the review id.
    event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{pr_url}:pr_reviewed:{review.get('id')}"))
    _capture_pr_review_event(payload, task_run, event_uuid)

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


# Nulled on external PRs so their schema matches task-originated PR events.
_TASK_ATTRIBUTION_KEYS = ("task_id", "run_id", "origin_product", "signal_report_id", "environment", "mode", "title")


def _account_type(payload: dict) -> str | None:
    """Whether the webhook's repo is owned by a GitHub org or a personal account.

    ``repository.owner.type`` is "Organization" or "User"; the top-level
    ``organization`` object is present only for org-owned repos and backs it up
    when the owner block is missing. Returns None when neither signal is present.
    """
    owner_type = ((payload.get("repository") or {}).get("owner") or {}).get("type")
    if owner_type == "Organization":
        return "organization"
    if owner_type == "User":
        return "personal"
    if payload.get("organization"):
        return "organization"
    return None


def _pr_payload_properties(payload: dict) -> dict:
    pull_request = payload.get("pull_request") or {}
    return {
        "pr_url": pull_request.get("html_url"),
        "pr_number": pull_request.get("number"),
        "pr_author": (pull_request.get("user") or {}).get("login"),
        "pr_base_ref": (pull_request.get("base") or {}).get("ref"),
        "pr_head_ref": (pull_request.get("head") or {}).get("ref"),
        "pr_additions": pull_request.get("additions"),
        "pr_deletions": pull_request.get("deletions"),
        "pr_changed_files": pull_request.get("changed_files"),
        "pr_commits": pull_request.get("commits"),
        "account_type": _account_type(payload),
        "repo_owner_type": ((payload.get("repository") or {}).get("owner") or {}).get("type"),
    }


# Cap the org-member lookup that attributes the merger (and reviewer). GitHub gives a
# pull_request delivery one short window and never retries it, and the merged branch runs
# functional side effects (merge bookkeeping, signal-report resolution, wizard wind-down)
# right after capture. A slow lookup on the request path can therefore cost the whole
# delivery, not just the analytics event. Bounding it degrades to no attribution instead.
_ATTRIBUTION_STATEMENT_TIMEOUT_MS = 800

# Models the org-member resolver reads. ReplicaRouter only sends a model to the replica when
# that model is named in READ_REPLICA_OPT_IN, so the set of aliases the lookup can touch is
# knowable up front.
_ATTRIBUTION_MODELS = (Team, User, OrganizationMembership, UserSocialAuth, UserIntegration, Integration)


def _attribution_db_aliases() -> list[str]:
    """The aliases the org-member lookup actually reads from, deduped, in model order.

    Bounding an alias means opening it, and opening is itself unbounded -- ``postgres_config``
    sets no ``connect_timeout`` on these aliases. So take the set from the router rather than
    assuming: reaching for an alias the resolver never uses could stall the webhook on
    connection setup before the cap is installed, which is the failure this exists to prevent.
    That cuts both ways -- a fully replica-opted deployment must not be made to wait on the
    primary either.
    """
    aliases: list[str] = []
    for model in _ATTRIBUTION_MODELS:
        alias = router.db_for_read(model) or "default"
        if alias not in aliases and alias in settings.DATABASES:
            aliases.append(alias)
    return aliases


def _read_statement_timeout(connection: BaseDatabaseWrapper) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    return row[0] if row else None


def _apply_statement_timeout(connection: BaseDatabaseWrapper, value: str) -> None:
    # set_config(..., is_local=True) is SET LOCAL, but takes the value as a bind parameter,
    # so a restored value ("30s", "0", ...) does not have to be quoted by hand.
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", [value])


@contextmanager
def _statement_timeout(connection: BaseDatabaseWrapper, timeout_ms: int, *, restore: bool) -> Iterator[None]:
    """Cap statements on one connection, optionally putting the previous value back."""
    previous = _read_statement_timeout(connection) if restore else None
    _apply_statement_timeout(connection, f"{timeout_ms}ms")

    yield

    # Only reached when the block succeeded. If it raised, the enclosing atomic() rolls the
    # (sub)transaction back and PostgreSQL undoes SET LOCAL with it, so there is nothing to
    # restore -- and a statement on an aborted transaction would error anyway.
    if previous:
        _apply_statement_timeout(connection, previous)


@contextmanager
def _bounded_attribution_lookup() -> Iterator[None]:
    """Run a block under a per-statement timeout on each configured DB the lookup may use.

    A read routed to an alias joins that alias's open transaction, so ``SET LOCAL
    statement_timeout`` there caps the query regardless of read-replica routing.
    """
    with ExitStack() as stack:
        for alias in _attribution_db_aliases():
            connection = connections[alias]
            # SET LOCAL dies with the transaction it was set in, so the cap only needs
            # restoring when we are joining a transaction somebody else owns -- a future
            # caller wrapping this in its own atomic block, or ATOMIC_REQUESTS (which
            # PostHog does not enable today). Otherwise the commit below ends it for us.
            restore = connection.in_atomic_block
            stack.enter_context(transaction.atomic(using=alias))
            stack.enter_context(_statement_timeout(connection, _ATTRIBUTION_STATEMENT_TIMEOUT_MS, restore=restore))
        yield


# PostgreSQL raises query_canceled when statement_timeout fires. Django wraps the driver
# error in OperationalError, so the SQLSTATE lives on the cause -- psycopg3 spells it
# `sqlstate`, psycopg2 `pgcode`. The message check is the fallback for anything that loses
# the cause on the way up.
_QUERY_CANCELED_SQLSTATE = "57014"


def _is_statement_timeout(error: Exception) -> bool:
    if not isinstance(error, OperationalError):
        return False
    cause = error.__cause__
    if getattr(cause, "sqlstate", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    if getattr(cause, "pgcode", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    return "statement timeout" in str(error).lower()


def _resolve_github_login_distinct_id(login: str | None, team_id: int) -> str | None:
    """Distinct id of the org member matching a GitHub login, or None when unresolvable.

    Runs under a per-statement timeout so a slow member lookup cannot hold the webhook
    open past GitHub's delivery timeout (see ``_ATTRIBUTION_STATEMENT_TIMEOUT_MS``).
    """
    if not login:
        return None
    try:
        with _bounded_attribution_lookup():
            resolved = resolve_org_github_login_to_users(team_id, [login]).get(str(login).strip().lower())
    except Exception as e:
        # timeout is meant to be the leading indicator for the cap we just installed, so it
        # has to mean "statement cancelled", not "any OperationalError" -- connection resets
        # and other DB incidents raise the same class and would drown the signal.
        outcome: GitHubWebhookAttributionOutcome = "timeout" if _is_statement_timeout(e) else "error"
        observe_github_webhook_attribution(outcome=outcome)
        logger.warning(
            "github_webhook_login_resolution_failed", login=login, team_id=team_id, outcome=outcome, error=str(e)
        )
        return None
    if resolved is None:
        observe_github_webhook_attribution(outcome="unresolved")
        return None
    observe_github_webhook_attribution(outcome="resolved")
    return str(resolved.distinct_id)


def _merged_by_attribution(payload: dict, team_id: int) -> tuple[dict, str | None]:
    """Identity of the GitHub user who merged the PR, resolved to a PostHog user when possible.

    Merging is the one unambiguous personal act in the loop, so when the merger's GitHub
    login maps to an org member the pr_merged event attributes to them. Without a match the
    event keeps the task's assigned user (an auto-resolved reviewer or fallback for
    auto-started reports), so a consumer tells the two apart by the presence of
    pr_merged_by_distinct_id.
    """
    merged_by = (payload.get("pull_request") or {}).get("merged_by") or {}
    login = merged_by.get("login")
    if not login:
        return {}, None
    properties: dict = {"pr_merged_by_login": login, "pr_merged_by_id": merged_by.get("id")}
    distinct_id = _resolve_github_login_distinct_id(login, team_id)
    if distinct_id is not None:
        properties["pr_merged_by_distinct_id"] = distinct_id
    return properties, distinct_id


def _capture_pr_review_event(payload: dict, task_run: TaskRun | None, event_uuid: str) -> None:
    review = payload.get("review") or {}
    reviewer = review.get("user") or {}
    login = reviewer.get("login")
    review_properties: dict = {
        "pr_review_state": review.get("state"),
        "pr_reviewed_by_login": login,
        "pr_reviewed_by_id": reviewer.get("id"),
    }
    pr_properties = {**_pr_payload_properties(payload), **review_properties}

    if task_run is not None:
        reviewer_distinct_id = _resolve_github_login_distinct_id(login, task_run.team_id)
        if reviewer_distinct_id is not None:
            pr_properties["pr_reviewed_by_distinct_id"] = reviewer_distinct_id
        captured = task_run.capture_event(
            "pr_reviewed",
            {**pr_properties, "pr_source": "task"},
            event_uuid=event_uuid,
            distinct_id_override=reviewer_distinct_id,
        )
        if not captured:
            observe_github_webhook_pr_event_dropped(analytics_event="pr_reviewed", reason="capture_exception")
        return

    team = _resolve_external_team(payload)
    if team is None:
        observe_github_webhook_pr_event_dropped(analytics_event="pr_reviewed", reason="unresolved_installation")
        logger.debug("github_pr_review_webhook_unresolved_installation", pr_url=pr_properties.get("pr_url"))
        return

    reviewer_distinct_id = _resolve_github_login_distinct_id(login, team.id)
    if reviewer_distinct_id is not None:
        pr_properties["pr_reviewed_by_distinct_id"] = reviewer_distinct_id

    properties: dict = {
        **pr_properties,
        "repository": ((payload.get("repository") or {}).get("full_name") or "").strip().lower() or None,
        "pr_source": "external",
        "team_id": team.id,
        # title omitted to avoid leaking customer business context.
        **dict.fromkeys(_TASK_ATTRIBUTION_KEYS, None),
    }

    try:
        posthoganalytics.capture(
            distinct_id=reviewer_distinct_id or str(team.uuid),
            event="pr_reviewed",
            properties=properties,
            groups=groups(team=team),
            uuid=event_uuid,
        )
    except Exception as e:
        observe_github_webhook_pr_event_dropped(analytics_event="pr_reviewed", reason="capture_exception")
        logger.warning("github_pr_review_webhook_capture_failed", error=str(e))


def _capture_pr_event(
    payload: dict, task_run: TaskRun | None, analytics_event: GitHubWebhookAnalyticsEvent, event_uuid: str
) -> None:
    pr_properties = _pr_payload_properties(payload)

    if task_run is not None:
        merger_distinct_id: str | None = None
        if analytics_event == "pr_merged":
            merged_by_properties, merger_distinct_id = _merged_by_attribution(payload, task_run.team_id)
            pr_properties = {**pr_properties, **merged_by_properties}
        captured = task_run.capture_event(
            analytics_event,
            {**pr_properties, "pr_source": "task"},
            event_uuid=event_uuid,
            distinct_id_override=merger_distinct_id,
        )
        if not captured:
            observe_github_webhook_pr_event_dropped(analytics_event=analytics_event, reason="capture_exception")
        return

    team = _resolve_external_team(payload)
    if team is None:
        observe_github_webhook_pr_event_dropped(analytics_event=analytics_event, reason="unresolved_installation")
        logger.debug("github_pr_webhook_unresolved_installation", pr_url=pr_properties.get("pr_url"))
        return

    external_distinct_id = str(team.uuid)
    if analytics_event == "pr_merged":
        merged_by_properties, merger_distinct_id = _merged_by_attribution(payload, team.id)
        pr_properties = {**pr_properties, **merged_by_properties}
        external_distinct_id = merger_distinct_id or external_distinct_id

    properties: dict = {
        **pr_properties,
        "repository": ((payload.get("repository") or {}).get("full_name") or "").strip().lower() or None,
        "pr_source": "external",
        "team_id": team.id,
        # title omitted to avoid leaking customer business context.
        **dict.fromkeys(_TASK_ATTRIBUTION_KEYS, None),
    }

    try:
        posthoganalytics.capture(
            distinct_id=external_distinct_id,
            event=analytics_event,
            properties=properties,
            groups=groups(team=team),
            uuid=event_uuid,
        )
    except Exception as e:
        observe_github_webhook_pr_event_dropped(analytics_event=analytics_event, reason="capture_exception")
        logger.warning("github_pr_webhook_capture_failed", analytics_event=analytics_event, error=str(e))


def _installation_id(payload: dict) -> str | None:
    """The delivery's GitHub App installation id, in the form the integration rows store it."""
    installation_id = (payload.get("installation") or {}).get("id")
    return None if installation_id is None else str(installation_id)


# The run lookup these feed reads TaskRun off the writer, and they run on the request path
# outside the bounded attribution block. Pin them to the writer too: a replica-opted
# Integration or Team would otherwise let a slow replica stall a delivery whose own lookup
# never needed it, and replica lag could hide a freshly connected installation.
_SCOPE_DB_ALIAS = "default"


def _installation_team_ids(payload: dict) -> list[int]:
    """Teams whose GitHub Integration matches the delivery's installation, in deterministic order.

    Empty when the payload carries no installation id or no Integration matches it — the
    lookups that take this fall back to their unscoped behaviour in that case.
    """
    external_id = _installation_id(payload)
    if external_id is None:
        return []

    # One installation can map to multiple teams; order_by makes attribution deterministic.
    return list(
        Integration.objects.using(_SCOPE_DB_ALIAS)
        .filter(kind="github", integration_id=external_id)
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )


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


def _resolve_external_team(payload: dict) -> Team | None:
    team_ids = _installation_team_ids(payload)
    if not team_ids:
        return None
    return Team.objects.filter(pk=team_ids[0]).first()


def _transition_signal_reports_for_task(
    task_id: uuid.UUID, pr_url: str, target_status: SignalReport.Status, success_log_event: str
) -> None:
    """Transition signal reports linked to a task's PR to ``target_status``.

    Covers both PR outcomes: a merged PR resolves its reports, a closed-unmerged PR archives
    (suppresses) them so they leave the inbox instead of lingering as if work were still pending.
    Kept tolerant: a single bad transition should not fail the whole webhook, since GitHub retries
    5xx responses and we've already acknowledged the PR event.
    """
    reports = (
        SignalReport.objects.filter(SignalReport.reports_for_task_filter(task_id))
        .exclude(
            status__in=[
                SignalReport.Status.RESOLVED,
                SignalReport.Status.DELETED,
                SignalReport.Status.SUPPRESSED,
            ]
        )
        .distinct()
    )

    for report in reports:
        try:
            updated_fields = report.transition_to(target_status)
        except InvalidStatusTransition:
            logger.warning(
                "github_pr_webhook_signal_report_invalid_transition",
                report_id=str(report.id),
                from_status=report.status,
                pr_url=pr_url,
            )
            continue
        report.save(update_fields=updated_fields)
        logger.info(
            success_log_event,
            report_id=str(report.id),
            task_id=str(task_id),
            pr_url=pr_url,
        )
