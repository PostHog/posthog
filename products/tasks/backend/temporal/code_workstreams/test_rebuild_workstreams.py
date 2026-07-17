import random
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from unittest.mock import patch

from django.utils import timezone

from posthog.models import Organization, Team, User

from products.tasks.backend.models import CodePrSnapshot, CodeWorkstream, Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.activities import rebuild_workstreams
from products.tasks.backend.temporal.code_workstreams.activities.rebuild_workstreams import (
    RebuildTeamWorkstreamsInput,
    _branch_resolution_pref,
    _build_pr_input,
    _repo_from_pr_url,
    _select_recent_task_ids,
    rebuild_team_workstreams,
)
from products.tasks.backend.temporal.code_workstreams.constants import ACTIVITY_WINDOW
from products.tasks.backend.temporal.process_task.utils import parse_run_state


def _snapshot(**overrides) -> CodePrSnapshot:
    defaults = {
        "pr_url": "https://github.com/org/repo/pull/1",
        "number": 1,
        "title": "PR",
        "state": "open",
        "ci_status": "passing",
        "review_decision": None,
        "unresolved_threads": 2,
        "mergeable": True,
        "author_login": "octocat",
        "requested_reviewer_logins": ["reviewer1"],
        "pr_updated_at": None,
    }
    defaults.update(overrides)
    return CodePrSnapshot(**defaults)


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"pr_base_branch": "master"}, "master"),
        ({"pr_base_branch": "main", "mode": "background"}, "main"),
        ({"mode": "background"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_parse_run_state_reads_pr_base_branch(state, expected):
    assert parse_run_state(state).pr_base_branch == expected


@pytest.mark.parametrize(
    "pr_url,expected",
    [
        ("https://github.com/posthog/posthog/pull/123", "posthog/posthog"),
        ("https://github.com/owner/repo/pull/1", "owner/repo"),
        ("https://github.enterprise.com/posthog/posthog/pull/9", "posthog/posthog"),
        ("not-a-url", None),
        ("https://github.com/onlyowner", None),
    ],
)
def test_repo_from_pr_url(pr_url, expected):
    assert _repo_from_pr_url(pr_url) == expected


def test_build_pr_input_carries_head_branch():
    pr = _build_pr_input(_snapshot(head_branch="feat/x"), set())
    assert pr.head_branch == "feat/x"


def test_branch_resolution_pref_prefers_open_then_recent():
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    closed_new = _snapshot(pr_url="c", state="closed", pr_updated_at=new)
    open_old = _snapshot(pr_url="a", state="open", pr_updated_at=old)
    open_new = _snapshot(pr_url="b", state="open", pr_updated_at=new)
    # Sorting ascending puts the winner last (last-wins when building the map).
    winner = sorted([closed_new, open_old, open_new], key=_branch_resolution_pref)[-1]
    assert winner.pr_url == "b"


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"home_quick_action": "Fix CI"}, "Fix CI"),
        ({"mode": "background"}, None),
        (None, None),
    ],
)
def test_parse_run_state_reads_home_quick_action(state, expected):
    assert parse_run_state(state).home_quick_action == expected


@pytest.mark.parametrize(
    "author_login,user_github_logins,expected",
    [
        ("octocat", {"octocat"}, True),
        ("octocat", {"octocat", "alt"}, True),
        ("octocat", {"someone-else"}, False),
        ("octocat", set(), False),
        (None, {"octocat"}, False),
    ],
)
def test_build_pr_input_is_author_requires_identity_match(author_login, user_github_logins, expected):
    pr = _build_pr_input(_snapshot(author_login=author_login), user_github_logins)
    assert pr.is_current_user_author is expected


@pytest.mark.parametrize(
    "requested_reviewer_logins,user_github_logins,expected",
    [
        (["alice", "bob"], {"bob"}, True),
        (["alice", "bob"], {"carol"}, False),
        ([], {"bob"}, False),
        (["alice"], set(), False),
    ],
)
def test_build_pr_input_is_requested_reviewer_requires_identity_match(
    requested_reviewer_logins, user_github_logins, expected
):
    pr = _build_pr_input(_snapshot(requested_reviewer_logins=requested_reviewer_logins), user_github_logins)
    assert pr.is_current_user_requested_reviewer is expected


def _org() -> Organization:
    return Organization.objects.create(name=f"WsOrg-{random.randint(1, 10**9)}")


def _team(org: Organization) -> Team:
    return Team.objects.create(organization=org, name=f"WsTeam-{random.randint(1, 10**9)}")


def _user(org: Organization) -> User:
    return User.objects.create_and_join(org, f"u{random.randint(1, 10**9)}@example.com", None)


def _task_with_run_at(
    team: Team,
    user: User,
    activity_at: datetime,
    branch: str | None = "feat/home",
    output: dict | None = None,
) -> Task:
    task = Task.objects.create(
        team=team, created_by=user, title="t", description="d", origin_product=Task.OriginProduct.USER_CREATED
    )
    run = TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.COMPLETED, branch=branch, output=output)
    # updated_at is auto_now, so set the activity timestamp with a bulk update to bypass it.
    TaskRun.objects.filter(id=run.id).update(updated_at=activity_at)
    return task


@pytest.mark.django_db
@freeze_time("2026-06-01")
def test_select_recent_task_ids_caps_per_user_and_keeps_low_volume_user():
    org = _org()
    team = _team(org)
    heavy = _user(org)
    light = _user(org)
    now = timezone.now()

    # Heavy user floods the team with 55 very recent tasks; only its freshest 50 should survive.
    heavy_tasks = [_task_with_run_at(team, heavy, now - timedelta(minutes=i)) for i in range(1, 56)]
    # Light user's older tasks must not be evicted by the heavy user's firehose.
    light_tasks = [_task_with_run_at(team, light, now - timedelta(hours=5, minutes=i)) for i in range(1, 4)]

    selected = set(_select_recent_task_ids(team.id, now - ACTIVITY_WINDOW))

    by_user = Counter(t.created_by_id for t in heavy_tasks + light_tasks if t.id in selected)
    assert by_user[heavy.id] == 50
    assert by_user[light.id] == 3

    # The dropped heavy-user tasks are its five oldest.
    dropped = {t.id for t in heavy_tasks if t.id not in selected}
    assert dropped == {t.id for t in heavy_tasks[-5:]}


@pytest.mark.django_db
@freeze_time("2026-06-01")
def test_select_recent_task_ids_applies_team_cap_across_users():
    org = _org()
    team = _team(org)
    now = timezone.now()
    for _ in range(3):
        user = _user(org)
        for i in range(1, 5):
            _task_with_run_at(team, user, now - timedelta(minutes=i))

    # Per-user cap admits all 12 tasks; the team cap is the ceiling that bounds the set.
    with patch.object(rebuild_workstreams, "MAX_TASKS_PER_TEAM", 7):
        selected = _select_recent_task_ids(team.id, now - ACTIVITY_WINDOW)

    assert len(selected) == 7


@pytest.mark.django_db
@freeze_time("2026-06-01")
def test_select_recent_task_ids_breaks_activity_ties_deterministically():
    org = _org()
    team = _team(org)
    user = _user(org)
    now = timezone.now()

    # More tied tasks than the cap: without a stable tie-breaker the rank-50 cutoff
    # shuffles between rebuilds and the prune deletes an unchanged task's workstream.
    tied = [_task_with_run_at(team, user, now - timedelta(hours=1)) for _ in range(55)]

    selected = _select_recent_task_ids(team.id, now - ACTIVITY_WINDOW)

    assert selected == sorted(t.id for t in tied)[:50]


@pytest.mark.django_db
@freeze_time("2026-06-01")
def test_select_recent_task_ids_ignores_tasks_that_cannot_form_workstreams():
    org = _org()
    team = _team(org)
    user = _user(org)
    now = timezone.now()

    # A fresh burst of lane-ineligible tasks (no PR, no feature branch) exceeds the cap...
    junk = [
        _task_with_run_at(team, user, now - timedelta(minutes=i), branch=branch)
        for i, branch in enumerate([None, "", "master", "main"] * 13, start=1)
    ]
    # ...but must not consume slots and evict the user's older lane-bearing tasks.
    branch_task = _task_with_run_at(team, user, now - timedelta(hours=2))
    pr_task = _task_with_run_at(
        team,
        user,
        now - timedelta(hours=3),
        branch=None,
        output={"pr_url": "https://github.com/org/repo/pull/1"},
    )

    selected = set(_select_recent_task_ids(team.id, now - ACTIVITY_WINDOW))

    assert branch_task.id in selected
    assert pr_task.id in selected
    assert selected.isdisjoint({t.id for t in junk})


@pytest.mark.django_db
@freeze_time("2026-06-01")
def test_rebuild_omits_run_with_merged_pr_without_snapshot():
    org = _org()
    team = _team(org)
    user = _user(org)
    _task_with_run_at(
        team,
        user,
        timezone.now() - timedelta(days=10),
        branch=None,
        output={"pr_url": "https://github.com/org/repo/pull/1", "pr_merged": True},
    )

    result = rebuild_team_workstreams(RebuildTeamWorkstreamsInput(team_id=team.id))

    assert result.workstreams == 0
    assert not CodeWorkstream.objects.for_team(team.id).filter(user=user).exists()
