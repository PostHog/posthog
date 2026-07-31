"""Match an incoming PR (by URL, or repository plus branch) back to the TaskRun that produced it.

Shared by the GitHub webhook backstop (`webhooks.py`) and the facade's
`find_signal_implementation_run`; lives in its own module so both can import it —
`webhooks.py` imports from the facade, so the facade importing `webhooks.py` back would be
a cycle.
"""

from django.db.models import Case, IntegerField, Value, When

from products.tasks.backend.models import TaskRun
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PREFIX

TASK_RUN_SELECT_RELATED = ("task", "task__created_by", "team")

TERMINAL_RUN_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)

DEAD_RUN_STATUSES = (TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def find_task_run(
    pr_url: str | None = None,
    branch: str | None = None,
    repository: str | None = None,
    *,
    team_id: int | None = None,
    exclude_dead: bool = False,
) -> TaskRun | None:
    repository = repository.strip() if repository else None

    def _scope(runs):
        # TaskRun has no team-scoped manager, so this spans every team, which the webhook backstop
        # needs. A caller that knows its team must filter first, or another team's run can win the pick.
        if team_id is not None:
            runs = runs.filter(team_id=team_id)
        # The self-driving carve-out may act only on a run that is still owned and didn't die, so
        # this drops failed/cancelled runs and soft-deleted tasks. COMPLETED stays in: success flips
        # the run to COMPLETED right after it opens the PR, and later pushes to that PR must keep
        # re-reviewing.
        if exclude_dead:
            runs = runs.filter(task__deleted=False).exclude(status__in=DEAD_RUN_STATUSES)
        return runs

    if pr_url:
        # A resumed wizard run inherits its predecessor's head branch, so a terminal
        # original and its live resume can both claim the same PR URL. Scope to the
        # webhook's repo and prefer non-terminal runs so merge handling lands on the
        # run that can still act on it.
        runs = _scope(TaskRun.objects.filter(output__pr_url=pr_url))
        if repository:
            runs = runs.filter(task__repository__iexact=repository)
        # Declared type keeps mypy happy: the annotated queryset yields an AnnotatedWith
        # variant that must not leak into the plain-queryset legs below.
        task_run: TaskRun | None = (
            runs.annotate(
                terminal_rank=Case(
                    When(status__in=TERMINAL_RUN_STATUSES, then=Value(1)),
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
            _scope(
                TaskRun.objects.filter(
                    branch=branch,
                    task__repository__iexact=repository,
                    state__wizard_head_branch__isnull=True,
                )
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
                _scope(
                    TaskRun.objects.filter(
                        state__wizard_head_branch=branch,
                        task__repository__iexact=repository,
                        task__deleted=False,
                    )
                )
                .exclude(status__in=TERMINAL_RUN_STATUSES)
                .select_related(*TASK_RUN_SELECT_RELATED)
                .first()
            )
            if task_run:
                return task_run

    return None
