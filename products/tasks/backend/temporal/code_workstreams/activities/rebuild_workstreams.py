from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from django.db.models import Max, Q
from django.utils import timezone

from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.user_integration import UserIntegration
from posthog.temporal.common.utils import close_db_connections

from products.tasks.backend.logic.code_workstreams.classify import pick_primary_situation
from products.tasks.backend.logic.code_workstreams.grouping import (
    PrInput,
    TaskInput,
    Workstream,
    branch_lookup_key,
    build_workstreams,
)
from products.tasks.backend.models import CodePrSnapshot, CodeWorkstream, Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.constants import ACTIVITY_WINDOW, MAX_TASKS_PER_TEAM
from products.tasks.backend.temporal.process_task.utils import parse_run_state


@dataclass
class RebuildTeamWorkstreamsInput:
    team_id: int


@dataclass
class RebuildTeamWorkstreamsOutput:
    users: int
    workstreams: int
    pruned: int


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _from_epoch_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _repo_name(full_path: Optional[str]) -> Optional[str]:
    if not full_path:
        return None
    return full_path.split("/")[-1]


def _pr_url_from_run(run: Optional[TaskRun]) -> Optional[str]:
    return (run.output or {}).get("pr_url") if run and run.output else None


def _task_to_input(task: Task) -> tuple[TaskInput, Optional[str]]:
    run: Optional[TaskRun] = task.latest_run
    last_activity = run.updated_at if run else task.updated_at
    cloud_pr_url = _pr_url_from_run(run)
    state = parse_run_state(run.state if run else None)
    return (
        TaskInput(
            id=str(task.id),
            title=task.title,
            status=run.status if run else None,
            last_activity_at=_epoch_ms(last_activity),
            repo_name=_repo_name(task.repository),
            repo_full_path=task.repository,
            branch=run.branch if run else None,
            base_branch=state.pr_base_branch,
            cloud_pr_url=cloud_pr_url,
            folder_path=None,
            quick_action=state.home_quick_action,
        ),
        cloud_pr_url,
    )


def _pr_wire(pr: PrInput) -> dict:
    return {
        "url": pr.url,
        "number": pr.number,
        "title": pr.title,
        "state": pr.state,
        "ciStatus": pr.ci_status,
        "reviewDecision": pr.review_decision,
        "unresolvedThreads": pr.unresolved_threads,
        "mergeable": pr.mergeable,
        "isCurrentUserRequestedReviewer": pr.is_current_user_requested_reviewer,
        "isCurrentUserAuthor": pr.is_current_user_author,
        "author": pr.author,
        "lastUpdatedAt": pr.last_updated_at,
    }


def _build_pr_input(snapshot: CodePrSnapshot, user_github_logins: set[str]) -> PrInput:
    author = snapshot.author_login
    reviewer_logins = snapshot.requested_reviewer_logins or []
    return PrInput(
        url=snapshot.pr_url,
        number=snapshot.number,
        title=snapshot.title,
        state=snapshot.state,
        ci_status=snapshot.ci_status,
        review_decision=snapshot.review_decision,
        unresolved_threads=snapshot.unresolved_threads,
        mergeable=snapshot.mergeable,
        is_current_user_requested_reviewer=bool(user_github_logins.intersection(reviewer_logins)),
        is_current_user_author=bool(author and author in user_github_logins),
        author=author,
        last_updated_at=_epoch_ms(snapshot.pr_updated_at) if snapshot.pr_updated_at else 0,
        head_branch=snapshot.head_branch,
    )


def _branch_resolution_pref(snapshot: CodePrSnapshot) -> tuple[int, float, str]:
    # Order so the best snapshot for a (repo, head_branch) collision is written last (last wins):
    # prefer still-open PRs over merged/closed (a reused branch's new PR beats the stale one),
    # then the most recently updated, with pr_url as a stable final tiebreaker.
    open_score = 1 if snapshot.state in ("open", "draft") else 0
    updated = snapshot.pr_updated_at.timestamp() if snapshot.pr_updated_at else 0.0
    return (open_score, updated, snapshot.pr_url)


def _repo_from_pr_url(pr_url: str) -> Optional[str]:
    # https://<host>/<owner>/<repo>/pull/<n> -> "<owner>/<repo>" (host-agnostic, covers enterprise).
    idx = pr_url.find("/pull/")
    if idx == -1:
        return None
    segments = [s for s in pr_url[:idx].split("/") if s]
    if len(segments) < 2:
        return None
    owner, repo = segments[-2], segments[-1]
    return f"{owner}/{repo}"


def _github_logins_by_user(user_ids: list[int]) -> dict[int, set[str]]:
    logins: dict[int, set[str]] = defaultdict(set)
    for user_id, config in UserIntegration.objects.filter(user_id__in=user_ids, kind="github").values_list(
        "user_id", "config"
    ):
        login = (config or {}).get("github_user", {}).get("login")
        if login:
            logins[user_id].add(login)
    return logins


@activity.defn
@close_db_connections
def rebuild_team_workstreams(input: RebuildTeamWorkstreamsInput) -> RebuildTeamWorkstreamsOutput:
    now = timezone.now()
    cutoff = now - ACTIVITY_WINDOW
    now_ms = _epoch_ms(now)

    # Group by task and order by most-recent activity so the MAX_TASKS_PER_TEAM cap deterministically
    # keeps the freshest tasks instead of an arbitrary slice that flickers between cycles.
    recent_task_ids = [
        row["task_id"]
        for row in TaskRun.objects.filter(team_id=input.team_id, updated_at__gte=cutoff)
        .values("task_id")
        .annotate(last_activity=Max("updated_at"))
        .order_by("-last_activity")[:MAX_TASKS_PER_TEAM]
    ]
    tasks = list(
        Task.objects.filter(id__in=recent_task_ids, team_id=input.team_id, archived=False, deleted=False)
        .select_related("created_by")
        .prefetch_related("runs")
    )

    by_user: dict[int, list[Task]] = defaultdict(list)
    needed_pr_urls: set[str] = set()
    needed_branches: set[str] = set()
    for task in tasks:
        if task.created_by_id is None:
            continue
        by_user[task.created_by_id].append(task)
        run = task.latest_run
        pr_url = _pr_url_from_run(run)
        if pr_url:
            needed_pr_urls.add(pr_url)
        # The branch a run actually worked on lets us link follow-up runs (no pr_url of
        # their own) to the open PR for that branch.
        if run and run.branch:
            needed_branches.add(run.branch)

    github_logins_by_user = _github_logins_by_user(list(by_user.keys()))

    total_workstreams = 0
    total_pruned = 0

    with team_scope(input.team_id):
        # Only load snapshots we will actually look up, so memory stays bounded by recent tasks
        # rather than the team's all-time snapshot count. We also pull snapshots whose head
        # branch matches a run's branch so branch-resolved grouping can find them.
        snapshots = list(
            CodePrSnapshot.objects.filter(team_id=input.team_id).filter(
                Q(pr_url__in=needed_pr_urls) | Q(head_branch__in=needed_branches)
            )
        )
        snapshots_by_url = {s.pr_url: s for s in snapshots}
        # Sorted so a (repo, head_branch) collision resolves deterministically (best wins last).
        snapshots_by_branch = sorted((s for s in snapshots if s.head_branch), key=_branch_resolution_pref)

        for user_id, user_tasks in by_user.items():
            user_github_logins = github_logins_by_user.get(user_id, set())
            task_inputs: list[TaskInput] = []
            pr_by_task: dict[str, PrInput] = {}
            pr_by_branch: dict[tuple[str, str], PrInput] = {}
            snapshot_id_by_url: dict[str, str] = {}
            for task in user_tasks:
                task_input, pr_url = _task_to_input(task)
                task_inputs.append(task_input)
                if pr_url and pr_url in snapshots_by_url:
                    snapshot = snapshots_by_url[pr_url]
                    pr_by_task[task_input.id] = _build_pr_input(snapshot, user_github_logins)
                    snapshot_id_by_url[pr_url] = str(snapshot.id)

            # is_current_user_author depends on the user, so the branch map is built per user.
            for snapshot in snapshots_by_branch:
                repo = _repo_from_pr_url(snapshot.pr_url)
                key = branch_lookup_key(repo, snapshot.head_branch)
                if key is None:
                    continue
                pr_by_branch[key] = _build_pr_input(snapshot, user_github_logins)
                snapshot_id_by_url[snapshot.pr_url] = str(snapshot.id)

            result = build_workstreams(task_inputs, pr_by_task, now_ms, pr_by_branch)
            live_keys: set[str] = set()
            for state, workstreams in (
                (CodeWorkstream.WorkstreamState.ATTENTION, result.needs_attention),
                (CodeWorkstream.WorkstreamState.IN_PROGRESS, result.in_progress),
            ):
                for ws in workstreams:
                    live_keys.add(ws.id)
                    _persist_workstream(input.team_id, user_id, state, ws, snapshot_id_by_url, now)
                    total_workstreams += 1

            pruned, _ = (
                CodeWorkstream.objects.filter(team_id=input.team_id, user_id=user_id)
                .exclude(key__in=live_keys)
                .delete()
            )
            total_pruned += pruned

    return RebuildTeamWorkstreamsOutput(
        users=len(by_user),
        workstreams=total_workstreams,
        pruned=total_pruned,
    )


def _persist_workstream(
    team_id: int,
    user_id: int,
    state: str,
    ws: Workstream,
    snapshot_id_by_url: dict[str, str],
    generated_at: datetime,
) -> None:
    CodeWorkstream.objects.update_or_create(
        team_id=team_id,
        user_id=user_id,
        key=ws.id,
        defaults={
            "repo_name": ws.repo_name,
            "repo_full_path": ws.repo_full_path,
            "branch": ws.branch,
            "pr_url": ws.pr_url,
            "pr_snapshot_id": snapshot_id_by_url.get(ws.pr_url) if ws.pr_url else None,
            "pr": _pr_wire(ws.pr) if ws.pr else None,
            "situations": list(ws.situations),
            "primary_situation": pick_primary_situation(ws.situations),
            "state": state,
            "tasks": [
                {"id": t.id, "title": t.title, "status": t.status, "quick_action": t.quick_action} for t in ws.tasks
            ],
            "last_activity_at": _from_epoch_ms(ws.last_activity_at),
            "generated_at": generated_at,
        },
    )
