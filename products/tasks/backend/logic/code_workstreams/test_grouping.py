from dataclasses import replace

import pytest

from products.tasks.backend.logic.code_workstreams.classify import STALE_THRESHOLD_MS
from products.tasks.backend.logic.code_workstreams.grouping import (
    RUNNING_STALE_THRESHOLD_MS,
    PrInput,
    TaskInput,
    build_workstreams,
    workstream_key,
)

NOW = 1_700_000_000_000


def _task(**overrides) -> TaskInput:
    return replace(
        TaskInput(
            id="t1",
            title="Task",
            status="completed",
            last_activity_at=NOW,
            repo_name="posthog",
            repo_full_path="posthog/posthog",
            branch="feat/x",
            cloud_pr_url=None,
            folder_path=None,
        ),
        **overrides,
    )


def _pr(**overrides) -> PrInput:
    return replace(
        PrInput(
            url="https://github.com/posthog/posthog/pull/1",
            number=1,
            title="PR",
            state="open",
            ci_status="passing",
            review_decision=None,
            unresolved_threads=0,
            mergeable=True,
            is_current_user_requested_reviewer=False,
            is_current_user_author=True,
            author="me",
            last_updated_at=NOW,
        ),
        **overrides,
    )


@pytest.mark.parametrize(
    "task,pr_url,expected",
    [
        (
            _task(branch="b", repo_name="r", repo_full_path="org/r", folder_path="/p"),
            "https://x/pull/9",
            "pr:https://x/pull/9",
        ),
        (_task(branch="b", repo_name="r", repo_full_path="org/r", folder_path="/p"), None, "branch:org/r#b"),
        (_task(branch="b", repo_name="r", repo_full_path=None, folder_path="/p"), None, "branch:r#b"),
        (_task(branch=None, repo_name=None, repo_full_path=None, folder_path="/p"), None, "path:/p"),
        (_task(branch=None, repo_name=None, repo_full_path=None, folder_path=None), None, None),
        # Branch equal to the base branch is not a real feature branch: don't group on it.
        (_task(branch="master", base_branch="master", folder_path=None), None, None),
        (_task(branch="master", base_branch="master", folder_path="/p"), None, "path:/p"),
        (_task(branch="master", base_branch="master"), "https://x/pull/9", "pr:https://x/pull/9"),
        # A branch distinct from the base branch still groups.
        (_task(branch="feat/x", base_branch="master", repo_full_path="org/r"), None, "branch:org/r#feat/x"),
    ],
)
def test_workstream_key_precedence(task, pr_url, expected):
    assert workstream_key(task, pr_url) == expected


def test_running_task_no_pr_is_excluded_from_workstreams():
    result = build_workstreams([_task(status="in_progress", branch=None, folder_path=None)], {}, NOW)
    assert not result.needs_attention
    assert not result.in_progress


def test_running_task_with_pr_is_grouped():
    task = _task(status="in_progress")
    result = build_workstreams([task], {task.id: _pr(ci_status="failing")}, NOW)
    assert len(result.needs_attention) == 1


def test_idle_running_task_falls_through_to_grouping():
    old = NOW - RUNNING_STALE_THRESHOLD_MS - 1
    task = _task(status="in_progress", last_activity_at=old)
    result = build_workstreams([task], {}, NOW)
    assert len(result.in_progress) == 1


def test_failing_ci_lands_in_needs_attention():
    task = _task()
    result = build_workstreams([task], {task.id: _pr(ci_status="failing")}, NOW)
    assert len(result.needs_attention) == 1
    ws = result.needs_attention[0]
    assert ws.pr_url == _pr().url
    assert "ci_failing" in ws.situations


def test_healthy_open_pr_lands_in_in_progress():
    task = _task()
    result = build_workstreams([task], {task.id: _pr()}, NOW)
    assert len(result.in_progress) == 1
    assert result.in_progress[0].situations == ["in_review"]


def test_tasks_group_by_shared_pr_url():
    url = "https://github.com/posthog/posthog/pull/42"
    t1 = _task(id="a", branch="x", last_activity_at=NOW)
    t2 = _task(id="b", branch="y", last_activity_at=NOW - 1000)
    pr_by_task = {"a": _pr(url=url), "b": _pr(url=url)}
    result = build_workstreams([t1, t2], pr_by_task, NOW)
    assert len(result.needs_attention) + len(result.in_progress) == 1
    ws = (result.needs_attention + result.in_progress)[0]
    assert {t.id for t in ws.tasks} == {"a", "b"}


def test_stale_branch_no_pr_is_attention():
    old = NOW - STALE_THRESHOLD_MS - 1
    task = _task(status="completed", last_activity_at=old, cloud_pr_url=None)
    result = build_workstreams([task], {}, NOW)
    assert len(result.needs_attention) == 1
    assert "stale" in result.needs_attention[0].situations


def test_task_without_grouping_key_is_skipped():
    task = _task(status="completed", branch=None, repo_name=None, folder_path=None, cloud_pr_url=None)
    result = build_workstreams([task], {}, NOW)
    assert not result.needs_attention
    assert not result.in_progress


def test_base_branch_no_pr_tasks_do_not_collapse_and_are_dropped():
    # Tasks that ran on the base branch and never pushed a feature branch or PR left no real
    # work to track, so they must neither collapse into one blob nor surface as workstreams.
    t1 = _task(id="a", branch="master", base_branch="master", cloud_pr_url=None)
    t2 = _task(id="b", branch="master", base_branch="master", cloud_pr_url=None)
    result = build_workstreams([t1, t2], {}, NOW)
    assert not result.needs_attention
    assert not result.in_progress


def test_tasks_group_by_shared_feature_branch():
    t1 = _task(id="a", branch="feat/x", base_branch="master", last_activity_at=NOW)
    t2 = _task(id="b", branch="feat/x", base_branch="master", last_activity_at=NOW - 1000)
    result = build_workstreams([t1, t2], {}, NOW)
    workstreams = result.needs_attention + result.in_progress
    assert len(workstreams) == 1
    assert {t.id for t in workstreams[0].tasks} == {"a", "b"}
    assert workstreams[0].branch == "feat/x"


def test_feature_branch_and_base_branch_tasks_do_not_merge():
    feature = _task(id="a", branch="feat/x", base_branch="master", cloud_pr_url=None)
    base = _task(id="b", branch="master", base_branch="master", cloud_pr_url=None)
    result = build_workstreams([feature, base], {}, NOW)
    workstreams = result.needs_attention + result.in_progress
    assert len(workstreams) == 1
    assert {t.id for t in workstreams[0].tasks} == {"a"}


def test_follow_up_task_resolves_to_pr_by_branch():
    # A follow-up run pushed to the PR's branch (branch == base, no own pr_url); it should still
    # group under the PR workstream via the branch→PR map and inherit its situation.
    url = "https://github.com/posthog/posthog/pull/7"
    follow_up = _task(
        id="b",
        repo_full_path="posthog/posthog",
        branch="feat/x",
        base_branch="feat/x",
        cloud_pr_url=None,
    )
    pr_by_branch = {("posthog/posthog", "feat/x"): _pr(url=url, ci_status="failing", head_branch="feat/x")}
    result = build_workstreams([follow_up], {}, NOW, pr_by_branch)
    assert len(result.needs_attention) == 1
    ws = result.needs_attention[0]
    assert ws.id == f"pr:{url}"
    assert "ci_failing" in ws.situations


def test_follow_up_task_groups_with_original_pr_task():
    url = "https://github.com/posthog/posthog/pull/7"
    original = _task(id="a", repo_full_path="posthog/posthog", branch="feat/x", cloud_pr_url=url)
    follow_up = _task(
        id="b",
        repo_full_path="posthog/posthog",
        branch="feat/x",
        base_branch="feat/x",
        cloud_pr_url=None,
    )
    pr_by_branch = {("posthog/posthog", "feat/x"): _pr(url=url, head_branch="feat/x")}
    result = build_workstreams([original, follow_up], {original.id: _pr(url=url)}, NOW, pr_by_branch)
    workstreams = result.needs_attention + result.in_progress
    assert len(workstreams) == 1
    assert {t.id for t in workstreams[0].tasks} == {"a", "b"}


def test_branch_resolution_is_repo_scoped():
    # A branch named "main" in one repo must not pull in a PR for "main" in another repo.
    url = "https://github.com/posthog/other/pull/1"
    task = _task(id="a", repo_full_path="posthog/posthog", branch="main", base_branch="main", cloud_pr_url=None)
    pr_by_branch = {("posthog/other", "main"): _pr(url=url, head_branch="main")}
    result = build_workstreams([task], {}, NOW, pr_by_branch)
    workstreams = result.needs_attention + result.in_progress
    assert not workstreams


def test_base_branch_task_does_not_resolve_to_base_headed_pr():
    # A no-op run on the base branch must not collapse into a PR that happens to be headed from
    # that base branch, while a real feature-branch follow-up still resolves.
    feature = _task(id="a", repo_full_path="posthog/posthog", branch="feat/x", base_branch="master", cloud_pr_url=None)
    base = _task(id="b", repo_full_path="posthog/posthog", branch="master", base_branch="master", cloud_pr_url=None)
    pr_by_branch = {
        ("posthog/posthog", "feat/x"): _pr(url="https://github.com/posthog/posthog/pull/1", head_branch="feat/x"),
        ("posthog/posthog", "master"): _pr(url="https://github.com/posthog/posthog/pull/2", head_branch="master"),
    }
    result = build_workstreams([feature, base], {}, NOW, pr_by_branch)
    workstreams = result.needs_attention + result.in_progress
    assert len(workstreams) == 1
    assert workstreams[0].id == "pr:https://github.com/posthog/posthog/pull/1"
    assert {t.id for t in workstreams[0].tasks} == {"a"}


def test_lone_base_branch_task_does_not_resolve_to_base_headed_pr():
    # Even with no sibling feature task to mark "master" a base branch, a lone run on the default
    # branch must not collapse into a PR that happens to be headed from "master".
    task = _task(id="a", repo_full_path="posthog/posthog", branch="master", base_branch="master", cloud_pr_url=None)
    pr_by_branch = {
        ("posthog/posthog", "master"): _pr(url="https://github.com/posthog/posthog/pull/2", head_branch="master")
    }
    result = build_workstreams([task], {}, NOW, pr_by_branch)
    workstreams = result.needs_attention + result.in_progress
    assert not workstreams


def test_quick_action_is_carried_onto_workstream_task():
    task = _task(id="a", quick_action="Fix CI")
    result = build_workstreams([task], {task.id: _pr(ci_status="failing")}, NOW)
    ws = result.needs_attention[0]
    assert ws.tasks[0].quick_action == "Fix CI"
