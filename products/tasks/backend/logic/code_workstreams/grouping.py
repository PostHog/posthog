from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Optional

from .classify import ClassifyInput, ClassifyPr, classify
from .situations import ATTENTION_SITUATIONS, SituationId

RUNNING_STATUSES = frozenset({"queued", "in_progress"})

RUNNING_STALE_THRESHOLD_MS = 30 * 60 * 1000


@dataclass
class TaskInput:
    id: str
    title: str
    status: Optional[str]
    last_activity_at: int
    repo_name: Optional[str] = None
    repo_full_path: Optional[str] = None
    branch: Optional[str] = None
    cloud_pr_url: Optional[str] = None
    folder_path: Optional[str] = None


@dataclass
class PrInput:
    url: str
    number: int
    title: str
    state: str
    ci_status: str
    review_decision: Optional[str]
    unresolved_threads: int
    mergeable: Optional[bool]
    is_current_user_requested_reviewer: bool
    is_current_user_author: bool
    author: Optional[str]
    last_updated_at: int


@dataclass
class WorkstreamTask:
    id: str
    title: str
    status: Optional[str]


@dataclass
class Workstream:
    id: str
    repo_name: Optional[str]
    repo_full_path: Optional[str]
    branch: Optional[str]
    pr_url: Optional[str]
    pr: Optional[PrInput]
    tasks: list[WorkstreamTask]
    situations: list[SituationId]
    last_activity_at: int


@dataclass
class WorkstreamsResult:
    needs_attention: list[Workstream] = field(default_factory=list)
    in_progress: list[Workstream] = field(default_factory=list)


def _is_running(status: Optional[str]) -> bool:
    return bool(status) and status in RUNNING_STATUSES


def _is_actively_running(task: TaskInput, now: int, has_pr: bool) -> bool:
    if not _is_running(task.status):
        return False
    if has_pr:
        return False
    return now - task.last_activity_at <= RUNNING_STALE_THRESHOLD_MS


def workstream_key(task: TaskInput, pr_url: Optional[str]) -> Optional[str]:
    if pr_url:
        return f"pr:{pr_url}"
    repo = task.repo_full_path or task.repo_name
    branch = task.branch
    if repo and branch:
        return f"branch:{repo}#{branch}"
    if task.folder_path:
        return f"path:{task.folder_path}"
    return None


def build_workstreams(
    tasks: list[TaskInput],
    pr_by_task: Mapping[str, PrInput],
    now: int,
) -> WorkstreamsResult:
    def pr_of(task: TaskInput) -> Optional[PrInput]:
        return pr_by_task.get(task.id)

    def pr_url_of(task: TaskInput) -> Optional[str]:
        snap = pr_of(task)
        if snap is not None:
            return snap.url
        return task.cloud_pr_url

    groups: dict[str, list[TaskInput]] = {}

    for task in tasks:
        pr_url = pr_url_of(task)
        if _is_actively_running(task, now, bool(pr_url)):
            continue
        key = workstream_key(task, pr_url)
        if not key:
            continue
        groups.setdefault(key, []).append(task)

    needs_attention: list[Workstream] = []
    in_progress: list[Workstream] = []

    for key, group_tasks in groups.items():
        group_tasks.sort(key=lambda t: t.last_activity_at, reverse=True)
        head = group_tasks[0]

        pr: Optional[PrInput] = None
        pr_url = None
        for t in group_tasks:
            snap = pr_of(t)
            url = snap.url if snap is not None else t.cloud_pr_url
            if url:
                pr = snap
                pr_url = url
                break

        branch = head.branch
        last_activity_at = head.last_activity_at

        situations = sorted(
            classify(
                ClassifyInput(
                    has_pr_url=bool(pr_url),
                    pr=_to_classify_pr(pr),
                    branch=branch,
                    last_activity_at=last_activity_at,
                    now=now,
                )
            )
        )

        workstream = Workstream(
            id=key,
            repo_name=head.repo_name,
            repo_full_path=head.repo_full_path,
            branch=branch,
            pr_url=pr_url,
            pr=pr,
            tasks=[WorkstreamTask(id=t.id, title=t.title, status=t.status) for t in group_tasks],
            situations=situations,
            last_activity_at=last_activity_at,
        )

        if any(s in ATTENTION_SITUATIONS for s in situations):
            needs_attention.append(workstream)
        else:
            in_progress.append(workstream)

    needs_attention.sort(key=lambda w: w.last_activity_at, reverse=True)
    in_progress.sort(key=lambda w: w.last_activity_at, reverse=True)

    return WorkstreamsResult(needs_attention=needs_attention, in_progress=in_progress)


def _to_classify_pr(pr: Optional[PrInput]) -> Optional[ClassifyPr]:
    if pr is None:
        return None
    return ClassifyPr(
        state=pr.state,  # type: ignore[arg-type]
        ci_status=pr.ci_status,  # type: ignore[arg-type]
        review_decision=pr.review_decision,  # type: ignore[arg-type]
        unresolved_threads=pr.unresolved_threads,
        is_current_user_author=pr.is_current_user_author,
        mergeable=pr.mergeable,
    )
